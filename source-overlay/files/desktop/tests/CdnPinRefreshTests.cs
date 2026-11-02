// Offline behavioral tests. This entry point never calls Download or Main.
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;

class CdnPinRefreshTests {
    static readonly BindingFlags Flags=BindingFlags.NonPublic|BindingFlags.Static;
    static Type Worker=typeof(LocalCdnWorker);
    static string Cache;
    static void Call(string name,params object[] args){Worker.GetMethod(name,Flags).Invoke(null,args);}
    static void Check(bool value,string message){if(!value)throw new Exception(message);}
    static void Save(uint uin,string address,string auth,double age=0) {
        var profile=new Dictionary<string,object>{{"uin",uin},{"auth_key",auth},{"addresses",new string[]{address}}};
        var record=new Dictionary<string,object>{{"uin",uin},{"created",DateTimeOffset.UtcNow.ToUnixTimeSeconds()-age},{"profiles",new object[]{profile}}};
        if(File.Exists(Cache))File.Delete(Cache); // This fixture's own synthetic record only.
        Call("Seal",Cache,record);
    }
    static void Admit(string address,uint uin,string auth,bool expected) {
        var fields=new Dictionary<string,byte[]>{{"weixinnum",System.Text.Encoding.ASCII.GetBytes(uin.ToString())},{"authkey",Hex(auth)}};
        bool allowed=true;try{Call("AdmitProfile",address,fields);}catch(TargetInvocationException){allowed=false;}
        Check(allowed==expected,"Unexpected pin admission");
    }
    static byte[] Hex(string value){var bytes=new byte[value.Length/2];for(int i=0;i<bytes.Length;i++)bytes[i]=Convert.ToByte(value.Substring(i*2,2),16);return bytes;}
    static int Main(string[] args) {
        try {
            string root=Path.GetFullPath(Path.Combine(args[0],"output/local-cdn-ipc/test"));Directory.CreateDirectory(root);
            Cache=Path.Combine(args[0],"output/databases/synthetic/_local_cdn_profile.dpapi.json");Directory.CreateDirectory(Path.GetDirectoryName(Cache));
            Worker.GetField("Root",Flags).SetValue(null,root);
            string oldAuth=new string('a',64),newAuth=new string('b',64);
            Save(1234,"8.8.8.8",oldAuth);Call("LoadPins",true);Admit("8.8.8.8",1234,oldAuth,true);
            Save(1234,"1.1.1.1",newAuth);Admit("1.1.1.1",1234,newAuth,true);
            Admit("9.9.9.9",1234,newAuth,false); // A job cannot authorize a destination.
            Admit("1.1.1.1",1234,oldAuth,false); // Identity must match this cached pin.
            Save(9999,"208.67.222.222",newAuth);Admit("208.67.222.222",9999,newAuth,false);
            Save(1234,"208.67.220.220",newAuth,90000);Admit("208.67.220.220",1234,newAuth,false);
            Save(1234,"127.0.0.1",newAuth);Admit("127.0.0.1",1234,newAuth,false);
            Save(1234,"4.2.2.2","invalid");Admit("4.2.2.2",1234,newAuth,false);
            Console.WriteLine("PASS: same-account DPAPI cache refresh, request-only destination denial, identity binding, unknown-account denial, expiry, private IP and malformed-auth rejection; no network calls.");
            return 0;
        }catch(Exception error){Console.Error.WriteLine("Pin refresh test failed: "+error.GetType().Name+":"+error.Message);return 1;}
    }
}
