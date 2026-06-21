using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;

internal static class VibelutionLauncher
{
    private static int Main(string[] args)
    {
        try
        {
            string projectDir = "";
            var forwardedArgs = new List<string>();
            for (int index = 0; index < args.Length; index++)
            {
                string arg = args[index] ?? "";
                if (arg.Equals("--project", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
                {
                    projectDir = args[++index];
                    continue;
                }
                forwardedArgs.Add(arg);
            }

            if (string.IsNullOrWhiteSpace(projectDir))
            {
                projectDir = Environment.CurrentDirectory;
            }
            projectDir = Path.GetFullPath(projectDir);

            string desktopEntryPath = Path.Combine(projectDir, "scripts", "vibelution_desktop_entry.vbs");
            if (!File.Exists(desktopEntryPath))
            {
                WriteFailure(projectDir, "Desktop entry script was not found: " + desktopEntryPath);
                return 2;
            }

            string action = forwardedArgs.Count > 0 ? forwardedArgs[0] : "launcher";
            var wscriptArgs = new List<string> { Quote(desktopEntryPath), action };
            for (int index = 1; index < forwardedArgs.Count; index++)
            {
                wscriptArgs.Add(forwardedArgs[index]);
            }

            string wscriptPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "wscript.exe");
            var startInfo = new ProcessStartInfo
            {
                FileName = wscriptPath,
                Arguments = string.Join(" ", wscriptArgs.ToArray()),
                WorkingDirectory = projectDir,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            };

            using (Process process = Process.Start(startInfo))
            {
                if (process == null)
                {
                    WriteFailure(projectDir, "Failed to start Windows Script Host.");
                    return 3;
                }
            }

            return 0;
        }
        catch (Exception ex)
        {
            string projectDir = Environment.CurrentDirectory;
            WriteFailure(projectDir, ex.ToString());
            return 1;
        }
    }

    private static string Quote(string value)
    {
        return "\"" + (value ?? "").Replace("\"", "\\\"") + "\"";
    }

    private static void WriteFailure(string projectDir, string message)
    {
        try
        {
            string logDir = Path.Combine(projectDir, ".runtime", "launcher");
            Directory.CreateDirectory(logDir);
            string logPath = Path.Combine(logDir, "native-launcher-entry.log");
            File.AppendAllText(
                logPath,
                DateTimeOffset.Now.ToString("o") + " " + message + Environment.NewLine
            );
        }
        catch
        {
        }
    }
}
