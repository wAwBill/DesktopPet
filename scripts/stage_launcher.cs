// ASCII-only so the .NET Framework csc on an English CI image can compile it.
// The root exe is this launcher. The real app lives in assets\_stage, because
// the already-shipped 1.1.0 updater only overwrites the assets directory.
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

internal static class StageLauncher
{
    [STAThread]
    private static void Main()
    {
        string baseDir = AppDomain.CurrentDomain.BaseDirectory;
        string staged = Path.Combine(baseDir, "assets", "_stage", "\u5c0f\u4ed3\u9f20\u684c\u5ba0.exe");
        if (!File.Exists(staged))
        {
            MessageBox.Show(
                "\u627e\u4e0d\u5230\u684c\u5ba0\u4e3b\u7a0b\u5e8f\uff08assets\\_stage\uff09\u3002\u8bf7\u91cd\u65b0\u89e3\u538b\u5b8c\u6574\u7684\u5b89\u88c5\u5305\u3002",
                "\u5c0f\u4ed3\u9f20\u684c\u5ba0",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return;
        }

        var args = Environment.GetCommandLineArgs();
        var psi = new ProcessStartInfo
        {
            FileName = staged,
            WorkingDirectory = baseDir,
            UseShellExecute = false,
            Arguments = QuoteArgs(args)
        };
        try
        {
            Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                "\u684c\u5ba0\u542f\u52a8\u5931\u8d25\uff1a" + ex.Message,
                "\u5c0f\u4ed3\u9f20\u684c\u5ba0",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
        }
    }

    private static string QuoteArgs(string[] args)
    {
        var sb = new StringBuilder();
        for (int i = 1; i < args.Length; i++)
        {
            if (sb.Length > 0)
                sb.Append(' ');
            string arg = args[i] ?? "";
            if (arg.IndexOfAny(new[] { ' ', '\t', '"' }) >= 0)
                sb.Append('"').Append(arg.Replace("\"", "\\\"")).Append('"');
            else
                sb.Append(arg);
        }
        return sb.ToString();
    }
}
