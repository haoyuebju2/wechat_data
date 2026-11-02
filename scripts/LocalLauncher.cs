using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
[assembly:System.Reflection.AssemblyVersion("0.1.0.0")]
class LocalLauncher {
    [STAThread] static int Main() {
        try {
            string root=AppDomain.CurrentDomain.BaseDirectory;
            string script=Path.Combine(root,"scripts","Start-Upstream-Offline.ps1");
            if(!File.Exists(script))throw new IOException("启动文件缺失，请检查安装目录。");
            var info=new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"WindowsPowerShell","v1.0","powershell.exe"),"-NoProfile -ExecutionPolicy Bypass -File \""+script+"\"");
            info.WorkingDirectory=root;info.UseShellExecute=false;info.CreateNoWindow=true;info.RedirectStandardOutput=true;info.RedirectStandardError=true;
            using(var process=Process.Start(info)) {
                // Drain both streams; no chat data or credentials are logged.
                var output=process.StandardOutput.ReadToEndAsync();var error=process.StandardError.ReadToEndAsync();
                process.WaitForExit();System.Threading.Tasks.Task.WaitAll(output,error);
                if(process.ExitCode!=0)throw new IOException("启动校验未通过。请先按安装说明配置防火墙；不要关闭系统隔离。");
            }
            return 0;
        }catch(Exception e){MessageBox.Show(e.Message,"微信数据本机工具",MessageBoxButtons.OK,MessageBoxIcon.Error);return 1;}
    }
}
