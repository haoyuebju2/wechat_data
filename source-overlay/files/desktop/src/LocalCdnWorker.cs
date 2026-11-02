// Dedicated file-IPC CDN carrier. No WeChat configuration/database/image-key
// access, no DNS, proxy, redirects, arbitrary URLs, process launch or logs.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;

class LocalCdnWorker {
    const int MaxReply=2*1024*1024;
    static string Root, Capability;
    static readonly JavaScriptSerializer Json=new JavaScriptSerializer{MaxJsonLength=8*1024*1024};
    static readonly HashSet<string> Keys=new HashSet<string>("ver weixinnum seq clientversion clientostype authkey nettype acceptdupack safeproto filetype wxchattype lastretcode ipseq largesvideo sourceflag wxautostart downpicformat rangestart rangeend wxmsgflag fileid".Split(' '));
    static readonly AutoResetEvent Wake=new AutoResetEvent(false);
    static readonly Dictionary<string,HashSet<string>> PinnedProfiles=new Dictionary<string,HashSet<string>>();
    static IntPtr Job;
    [StructLayout(LayoutKind.Sequential)] struct Basic {public long A,B;public uint Flags;public UIntPtr Min,Max;public uint Processes;public UIntPtr Affinity;public uint Priority,Schedule;}
    [StructLayout(LayoutKind.Sequential)] struct IO {public ulong A,B,C,D,E,F;}
    [StructLayout(LayoutKind.Sequential)] struct Extended {public Basic Basic;public IO IO;public UIntPtr Memory,JobMemory,Peak,JobPeak;}
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] static extern IntPtr CreateJobObject(IntPtr security,string name);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool SetInformationJobObject(IntPtr job,int kind,ref Extended value,uint size);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr job,IntPtr process);
    static void Restrict() {
        Job=CreateJobObject(IntPtr.Zero,null);
        var limits=new Extended();limits.Basic.Flags=8|0x100;limits.Basic.Processes=1;limits.Memory=new UIntPtr(256*1024*1024);
        if(Job==IntPtr.Zero) throw new InvalidOperationException("job_create");
        if(!SetInformationJobObject(Job,9,ref limits,(uint)Marshal.SizeOf(limits))) throw new InvalidOperationException("job_config_"+Marshal.GetLastWin32Error());
        if(!AssignProcessToJobObject(Job,Process.GetCurrentProcess().Handle)) throw new InvalidOperationException("job_assign_"+Marshal.GetLastWin32Error());
    }
    static bool Same(string a,string b) {
        if(a==null || b==null || a.Length!=b.Length) return false;
        int delta=0;for(int i=0;i<a.Length;i++) delta|=a[i]^b[i];return delta==0;
    }
    static void LocalPath(string path) {
        string full=Path.GetFullPath(path);
        if(full.StartsWith(@"\\") || new DriveInfo(Path.GetPathRoot(full)).DriveType!=DriveType.Fixed) throw new InvalidDataException();
        for(string p=full;p!=null;p=Path.GetDirectoryName(p))
            if((File.Exists(p)||Directory.Exists(p)) && (File.GetAttributes(p)&FileAttributes.ReparsePoint)!=0) throw new InvalidDataException();
    }
    static Dictionary<string,object> Open(string file) {
        LocalPath(file);
        if(new FileInfo(file).Length>131072) throw new InvalidDataException();
        var envelope=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(file,Encoding.UTF8));
        if((string)envelope["format"]!="windows-dpapi-user/1") throw new InvalidDataException();
        byte[] plain=ProtectedData.Unprotect(Convert.FromBase64String((string)envelope["encrypted"]),null,DataProtectionScope.CurrentUser);
        try{return Json.Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(plain));}
        finally{Array.Clear(plain,0,plain.Length);}
    }
    static void Seal(string file,Dictionary<string,object> value) {
        LocalPath(file);
        byte[] plain=Encoding.UTF8.GetBytes(Json.Serialize(value));
        byte[] cipher=ProtectedData.Protect(plain,null,DataProtectionScope.CurrentUser);
        Array.Clear(plain,0,plain.Length);
        string temporary=file+".tmp";
        LocalPath(temporary);
        File.WriteAllText(temporary,Json.Serialize(new Dictionary<string,object>{{"format","windows-dpapi-user/1"},{"encrypted",Convert.ToBase64String(cipher)}}),new UTF8Encoding(false));
        if(File.Exists(file)) throw new InvalidDataException();
        File.Move(temporary,file);
        Array.Clear(cipher,0,cipher.Length);
    }
    static bool PublicIPv4(string text) {
        IPAddress ip;if(!IPAddress.TryParse(text,out ip)||ip.AddressFamily!=System.Net.Sockets.AddressFamily.InterNetwork||ip.ToString()!=text)return false;
        byte[] b=ip.GetAddressBytes();
        return b[0]>0&&b[0]<224&&b[0]!=10&&b[0]!=127&&!(b[0]==169&&b[1]==254)&&!(b[0]==172&&b[1]>=16&&b[1]<=31)&&!(b[0]==192&&b[1]==168)&&!(b[0]==100&&b[1]>=64&&b[1]<=127)&&!(b[0]==198&&(b[1]==18||b[1]==19));
    }
    static int Integer(byte[] b,int pos) {
        if(pos<0||pos+4>b.Length)throw new InvalidDataException();
        uint n=(uint)b[pos]<<24|(uint)b[pos+1]<<16|(uint)b[pos+2]<<8|b[pos+3];
        if(n>Int32.MaxValue)throw new InvalidDataException();return (int)n;
    }
    static Dictionary<string,byte[]> ValidatePacket(byte[] body,int sequence) {
        if(body.Length<16||body.Length>65536)throw new InvalidDataException();
        var fields=new Dictionary<string,byte[]>();int pos=0;
        while(pos<body.Length) {
            int n=Integer(body,pos);pos+=4;if(n<1||n>32||pos+n+4>body.Length)throw new InvalidDataException();
            string key=Encoding.ASCII.GetString(body,pos,n);pos+=n;
            n=Integer(body,pos);pos+=4;if(n<0||n>8192||pos+n>body.Length||!Keys.Contains(key)||fields.ContainsKey(key))throw new InvalidDataException();
            byte[] value=new byte[n];Buffer.BlockCopy(body,pos,value,0,n);pos+=n;fields.Add(key,value);
        }
        string fileType=Encoding.ASCII.GetString(fields["filetype"]),pictureFormat=Encoding.ASCII.GetString(fields["downpicformat"]);
        if(fields.Count!=Keys.Count||fields["authkey"].Length<16||fields["authkey"].Length>4096||Encoding.ASCII.GetString(fields["seq"])!=sequence.ToString()||(fileType!="1"&&fileType!="2")||(pictureFormat!="1"&&pictureFormat!="2")||!Regex.IsMatch(Encoding.ASCII.GetString(fields["fileid"]),"\\A[0-9a-fA-F]{20,8192}\\z"))throw new InvalidDataException();
        long start,end;
        if(!Int64.TryParse(Encoding.ASCII.GetString(fields["rangestart"]),out start)||!Int64.TryParse(Encoding.ASCII.GetString(fields["rangeend"]),out end)||start<0||start>25*1024*1024||end!=start+65535)throw new InvalidDataException();
        return fields;
    }
    static void LoadPins(bool initial) {
        // Snapshot destinations independently from the encrypted profile cache,
        // never admit a new destination merely because a request names it.
        string accounts=Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"../../output/databases"));
        LocalPath(accounts);if(!Directory.Exists(accounts))return;
        foreach(string directory in Directory.EnumerateDirectories(accounts)) {
            string file=Path.Combine(directory,"_local_cdn_profile.dpapi.json");
            if(!File.Exists(file))continue;
            try {
                var record=Open(file);double age=DateTimeOffset.UtcNow.ToUnixTimeSeconds()-Convert.ToDouble(record["created"]);
                if(age<0||age>=86400)continue;
                foreach(Dictionary<string,object> profile in (IEnumerable)record["profiles"]) {
                    string identity=Convert.ToString(profile["uin"])+":"+(string)profile["auth_key"];
                    foreach(string address in (IEnumerable)profile["addresses"]) {
                        if(!PublicIPv4(address))continue;
                        if(!PinnedProfiles.ContainsKey(address)){if(!initial)continue;PinnedProfiles[address]=new HashSet<string>();}
                        if(initial||PinnedProfiles[address].Count<16)PinnedProfiles[address].Add(identity);
                    }
                }
            }catch{}
        }
    }
    static void AdmitProfile(string address,Dictionary<string,byte[]> fields) {
        if(PinnedProfiles.Count==0)LoadPins(true);
        string identity=Encoding.ASCII.GetString(fields["weixinnum"])+":"+BitConverter.ToString(fields["authkey"]).Replace("-","").ToLowerInvariant();
        if(PinnedProfiles.ContainsKey(address)&&!PinnedProfiles[address].Contains(identity))LoadPins(false);
        if(!PinnedProfiles.ContainsKey(address)||!PinnedProfiles[address].Contains(identity))throw new InvalidDataException();
    }
    static byte[] Download(string address,byte[] body,int sequence) {
        var clock=Stopwatch.StartNew();
        var request=(HttpWebRequest)WebRequest.Create("http://"+address+":443/download");
        request.Proxy=null;request.AllowAutoRedirect=false;request.Method="POST";request.Timeout=6000;request.ReadWriteTimeout=6000;
        request.KeepAlive=false;request.ContentType="application/octet-stream";request.UserAgent="MicroMessenger Client";request.Accept="*/*";
        request.Headers["C-Seq"]=sequence.ToString();request.ContentLength=body.Length;
        try {
            using(var output=request.GetRequestStream())output.Write(body,0,body.Length);
            HttpWebResponse received;
            try{received=(HttpWebResponse)request.GetResponse();}
            catch(WebException error){
                received=error.Response as HttpWebResponse;
                // CDN application errors can be a bounded TLV body under HTTP
                // 400. Let the backend inspect retcode instead of hiding it.
                if(received==null||received.StatusCode!=HttpStatusCode.BadRequest){if(received!=null)received.Dispose();throw;}
            }
            using(var response=received) {
                if((response.StatusCode!=HttpStatusCode.OK&&response.StatusCode!=HttpStatusCode.BadRequest)||response.ContentLength>MaxReply)throw new InvalidDataException();
                using(var input=response.GetResponseStream())using(var result=new MemoryStream()) {
                    byte[] buffer=new byte[32768];
                    while(true) {
                        if(clock.ElapsedMilliseconds>10000)throw new TimeoutException();
                        int n=input.Read(buffer,0,buffer.Length);if(n==0)break;
                        if(result.Length+n>MaxReply)throw new InvalidDataException();result.Write(buffer,0,n);
                    }
                    return result.ToArray();
                }
            }
        }finally{request.Abort();}
    }
    static void Handle(string file) {
        string name=Path.GetFileName(file);
        if(!Regex.IsMatch(name,"\\A[0-9a-f]{32}\\.request\\.dpapi\\.json\\z"))return;
        string response=Path.Combine(Root,name.Replace(".request.",".response."));
        if(File.Exists(response))return;
        var result=new Dictionary<string,object>{{"ok",false}};
        try {
            var job=Open(file);
            if(!Same((string)job["capability"],Capability)||(string)job["provenance"]!="account_matched_resident_cdndns_protobuf")throw new InvalidDataException();
            long expires=Convert.ToInt64(job["expires"]),now=DateTimeOffset.UtcNow.ToUnixTimeSeconds();
            if(expires<now||expires>now+90)throw new InvalidDataException();
            string address=(string)job["address"];bool admitted=false;int count=0;
            foreach(object candidate in (IEnumerable)job["allowed_addresses"]) {if(++count>16||!PublicIPv4((string)candidate))throw new InvalidDataException();if((string)candidate==address)admitted=true;}
            if(!admitted||!PublicIPv4(address))throw new InvalidDataException();
            int sequence=Convert.ToInt32(job["sequence"]);if(sequence<1||sequence>402)throw new InvalidDataException();
            byte[] body=Convert.FromBase64String((string)job["body_b64"]);var fields=ValidatePacket(body,sequence);AdmitProfile(address,fields);
            byte[] bytes=Download(address,body,sequence);
            result["ok"]=true;result["response_b64"]=Convert.ToBase64String(bytes);
            Array.Clear(body,0,body.Length);Array.Clear(bytes,0,bytes.Length);
        }catch{result=new Dictionary<string,object>{{"ok",false}};}
        try{if(File.Exists(file)){Seal(response,result);if(!File.Exists(file))File.Delete(response);}}catch{}
    }
    static int Main(string[] args) {
        string stage="isolation";
        try {
            Restrict();stage="root";if(args.Length!=1)throw new InvalidDataException();Root=Path.GetFullPath(args[0]);LocalPath(Root);
            stage="capability";
            Capability=Console.ReadLine();if(Capability==null||!Regex.IsMatch(Capability,"\\A[0-9a-f]{64}\\z"))throw new InvalidDataException();
            Directory.CreateDirectory(Root);LoadPins(true);stage="ready";
            using(var hash=SHA256.Create())File.WriteAllText(Path.Combine(Root,"ready.json"),Json.Serialize(new Dictionary<string,object>{{"pid",Process.GetCurrentProcess().Id},{"capability_sha256",BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(Capability))).Replace("-","").ToLowerInvariant()}}),new UTF8Encoding(false));
            using(var watcher=new FileSystemWatcher(Root,"*.request.dpapi.json")) {
                watcher.Created+=(s,e)=>Wake.Set();watcher.Changed+=(s,e)=>Wake.Set();watcher.Renamed+=(s,e)=>Wake.Set();watcher.EnableRaisingEvents=true;
                while(true){int count=0;foreach(string file in Directory.EnumerateFiles(Root,"*.request.dpapi.json")){if(++count>128)break;Handle(file);}Wake.WaitOne(1000);}
            }
        }catch(Exception error){Console.Error.WriteLine("local_cdn_worker_start_failed:"+stage+":"+error.GetType().Name+(stage=="isolation"?":"+error.Message:""));return 1;}
    }
}
