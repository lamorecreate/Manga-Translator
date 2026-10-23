using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

class Program
{
    [STAThread]
    static void Main()
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        string native = Path.Combine(dir, "native", "MangaTranslator.exe");
        string bat = Path.Combine(dir, "start.bat");
        try
        {
            if (File.Exists(native))
            {
                var psi = new ProcessStartInfo(native)
                {
                    WorkingDirectory = dir,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };
                psi.EnvironmentVariables["MT_APP_ROOT"] = dir;
                psi.EnvironmentVariables["MT_NO_BROWSER"] = "1";
                var child = Process.Start(psi);
                if (child != null)
                {
                    if (child.WaitForExit(1500) && child.ExitCode != 0)
                        MessageBox.Show("原生窗口启动失败（代码 " + child.ExitCode + "）。\n请查看 data\\crash.log，或运行 start.bat 查看日志。", "漫画译站");
                }
                return;
            }
            if (File.Exists(bat))
            {
                var psi = new ProcessStartInfo("cmd.exe", "/c \"" + bat + "\"")
                {
                    WorkingDirectory = dir,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };
                psi.EnvironmentVariables["MT_NO_PAUSE"] = "1";
                Process.Start(psi);
                return;
            }
            MessageBox.Show("找不到 native\\MangaTranslator.exe 或 start.bat。请把整个程序文件夹完整复制。", "漫画译站");
        }
        catch (Exception e)
        {
            MessageBox.Show("启动失败：" + e.Message, "漫画译站");
        }
    }
}
