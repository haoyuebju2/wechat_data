using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
[assembly:AssemblyVersion("0.1.0.0")]
class ReleaseInstaller:Form {
    static readonly JavaScriptSerializer Json=new JavaScriptSerializer{MaxJsonLength=2000000};
    TextBox location=new TextBox{Left=20,Top=105,Width=535};
    TextBox log=new TextBox{Left=20,Top=200,Width=635,Height=230,Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Vertical};
    CheckBox autoStart=new CheckBox{Left=20,Top=147,Width=430,Text="登录 Windows 后自动启动（可选）"};
    Button install=new Button{Left=500,Top=450,Width=155,Text="安装 0.1.0"};
    bool busy=false;
    static byte[] Resource(string name){using(var input=Assembly.GetExecutingAssembly().GetManifestResourceStream(name))using(var output=new MemoryStream()){if(input==null)throw new InvalidDataException("Missing installer resource");input.CopyTo(output);return output.ToArray();}}
    static string Hash(byte[] data){using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(data)).Replace("-","").ToLowerInvariant();}
    public static Dictionary<string,object> Manifest(){return Json.Deserialize<Dictionary<string,object>>(System.Text.Encoding.UTF8.GetString(Resource("release-manifest.json")));}
    static void LocalTarget(string path){
        if(path.StartsWith(@"\\")||path.IndexOf('"')>=0||path.Substring(2).Contains(":"))throw new IOException("请选择本机固定磁盘目录。");
        if(new DriveInfo(Path.GetPathRoot(path)).DriveType!=DriveType.Fixed)throw new IOException("请选择本机固定磁盘。");
        for(string current=path;!String.IsNullOrEmpty(current);current=Path.GetDirectoryName(current))if((Directory.Exists(current)||File.Exists(current))&&(File.GetAttributes(current)&FileAttributes.ReparsePoint)!=0)throw new IOException("安装路径不能包含链接或重解析目录。");
        if(File.Exists(path)||(Directory.Exists(path)&&Directory.GetFileSystemEntries(path).Length!=0))throw new IOException("安装目录非空。请选择新目录；旧版本和数据不会被覆盖。");
    }
    public static void Extract(string target){
        target=Path.GetFullPath(target).TrimEnd(Path.DirectorySeparatorChar);LocalTarget(target);
        var manifest=Manifest();byte[] payload=Resource("release-payload.zip");
        if(Hash(payload)!=(string)manifest["payload_sha256"])throw new InvalidDataException("Installer payload checksum mismatch");
        var files=(Dictionary<string,object>)manifest["files"];var seen=new HashSet<string>(StringComparer.OrdinalIgnoreCase);long total=0;
        using(var archive=new ZipArchive(new MemoryStream(payload),ZipArchiveMode.Read)){
            // Validate every member before creating any destination files.
            foreach(var entry in archive.Entries){
                string name=entry.FullName;
                if(name.Contains("\\")||name.Contains(":")||name.StartsWith("/")||name.Split('/').Length>24||Array.Exists(name.Split('/'),part=>part==".."||part=="."||part=="")||!files.ContainsKey(name)||!seen.Add(name)||entry.Length>10000000||(total+=entry.Length)>30000000)throw new InvalidDataException("Unsafe installer member");
                using(var input=entry.Open())using(var content=new MemoryStream()){input.CopyTo(content);if(Hash(content.ToArray())!=(string)files[name])throw new InvalidDataException("Source checksum mismatch");}
            }
            if(seen.Count!=files.Count)throw new InvalidDataException("Incomplete installer payload");
            Directory.CreateDirectory(target);
            foreach(var entry in archive.Entries){
                string destination=Path.GetFullPath(Path.Combine(target,entry.FullName.Replace('/',Path.DirectorySeparatorChar)));
                if(!destination.StartsWith(target+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new InvalidDataException("Invalid extraction boundary");
                Directory.CreateDirectory(Path.GetDirectoryName(destination));
                using(var input=entry.Open())using(var output=new FileStream(destination,FileMode.CreateNew,FileAccess.Write))input.CopyTo(output);
            }
        }
    }
    ReleaseInstaller(){
        Text="微信数据本机工具 0.1.0 · 联网安装器";Width=700;Height=540;FormBorderStyle=FormBorderStyle.FixedDialog;MaximizeBox=false;StartPosition=FormStartPosition.CenterScreen;
        Controls.Add(new Label{Left=20,Top=20,Width=640,Height=70,Text="首次安装需要联网，自动下载并校验项目专用运行环境。\n只使用新的空目录；不会读取微信数据，不会覆盖旧版。\n最后配置防火墙时需要管理员确认。安装包未进行代码签名。"});
        location.Text=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"WeChatDataMonitor","0.1.0");Controls.Add(location);Controls.Add(log);Controls.Add(autoStart);Controls.Add(install);
        var browse=new Button{Left=565,Top=103,Width=90,Text="选择目录"};Controls.Add(browse);
        browse.Click+=(s,e)=>{if(busy)return;using(var dialog=new FolderBrowserDialog()){if(dialog.ShowDialog()==DialogResult.OK)location.Text=dialog.SelectedPath;}};
        FormClosing+=(s,e)=>{if(busy){e.Cancel=true;MessageBox.Show("安装仍在进行，请等待结束。","安装");}};
        install.Click+=async(s,e)=>{
            if(busy)return;string target;
            try{target=Path.GetFullPath(location.Text);}catch{MessageBox.Show("安装目录无效，请重新选择。");return;}
            bool automatic=autoStart.Checked;busy=true;install.Enabled=false;location.Enabled=false;autoStart.Enabled=false;
            try{
                await Task.Run(()=>{
                    Extract(target);Append("源码包校验完成，开始准备运行环境。\r\n");
                    var info=new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"WindowsPowerShell","v1.0","powershell.exe"),"-NoProfile -ExecutionPolicy Bypass -File \""+Path.Combine(target,"scripts","Install-Release.ps1")+"\""+(automatic?" -EnableAutoStart":""));
                    info.WorkingDirectory=target;info.UseShellExecute=false;info.CreateNoWindow=true;info.RedirectStandardOutput=true;info.RedirectStandardError=true;
                    using(var process=new Process{StartInfo=info}){
                        process.OutputDataReceived+=(a,b)=>{if(b.Data!=null)Append(b.Data+"\r\n");};process.ErrorDataReceived+=(a,b)=>{if(b.Data!=null)Append(b.Data+"\r\n");};
                        process.Start();process.BeginOutputReadLine();process.BeginErrorReadLine();process.WaitForExit();
                        if(process.ExitCode!=0)throw new IOException("安装未完成，请查看安装输出。保留了已写入文件；重试请使用新目录，勿覆盖数据。");
                    }
                });
                MessageBox.Show("安装完成。请从桌面快捷方式或安装目录的 WeChatDataMonitor.exe 启动。","安装完成");
            }catch(Exception error){MessageBox.Show(error.Message,"安装未完成",MessageBoxButtons.OK,MessageBoxIcon.Error);}
            finally{busy=false;install.Enabled=true;location.Enabled=true;autoStart.Enabled=true;}
        };
    }
    void Append(string line){if(IsHandleCreated)BeginInvoke((Action)(()=>log.AppendText(line)));}
    [STAThread] static int Main(string[] args){
        if(args.Length>0){try{
            if(args.Length==2&&args[0]=="--extract-only"){Extract(args[1]);return 0;}
            if(args.Length==2&&args[0]=="--verify-payload"){var m=Manifest();if(Hash(Resource("release-payload.zip"))!=(string)m["payload_sha256"])throw new InvalidDataException();File.WriteAllText(args[1],Json.Serialize(m));return 0;}
            return 2;
        }catch{return 1;}}
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);Application.Run(new ReleaseInstaller());return 0;
    }
}
