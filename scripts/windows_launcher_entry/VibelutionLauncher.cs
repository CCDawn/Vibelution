using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;

internal static class VibelutionLauncher
{
    [STAThread]
    private static int Main(string[] args)
    {
        string projectDir = Environment.CurrentDirectory;
        try
        {
            var parsed = ParseArgs(args);
            projectDir = parsed.ProjectDir;
            string action = parsed.ForwardedArgs.Count > 0 ? parsed.ForwardedArgs[0] : "launcher";
            if (!action.Equals("launcher", StringComparison.OrdinalIgnoreCase))
            {
                return RunLegacyScriptAction(projectDir, parsed.ForwardedArgs);
            }

            bool created;
            using (var mutex = new Mutex(true, "Global\\Vibelution.Launcher.Tray", out created))
            {
                if (!created)
                {
                    RunPythonBridge(projectDir, "launcher", false, false);
                    return 0;
                }

                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new TrayApplicationContext(projectDir));
            }
            return 0;
        }
        catch (Exception ex)
        {
            WriteFailure(projectDir, ex.ToString());
            return 1;
        }
    }

    private sealed class ParsedArgs
    {
        public string ProjectDir;
        public List<string> ForwardedArgs;
    }

    private sealed class TrayApplicationContext : ApplicationContext
    {
        private readonly string projectDir;
        private readonly string launcherUrl;
        private readonly NotifyIcon notifyIcon;
        private readonly SynchronizationContext uiContext;

        public TrayApplicationContext(string projectDir)
        {
            this.projectDir = projectDir;
            this.launcherUrl = "http://127.0.0.1:" + LauncherControlPort(projectDir).ToString();
            this.uiContext = SynchronizationContext.Current ?? new WindowsFormsSynchronizationContext();
            this.notifyIcon = new NotifyIcon();
            this.notifyIcon.Text = "Vibelution Launcher";
            this.notifyIcon.Icon = LoadTrayIcon(projectDir);
            this.notifyIcon.ContextMenuStrip = BuildMenu();
            this.notifyIcon.Visible = true;
            this.notifyIcon.DoubleClick += delegate { QueueOpenConsole(); };
            ThreadPool.QueueUserWorkItem(delegate { BootstrapLauncherBackend(); });
        }

        private ContextMenuStrip BuildMenu()
        {
            var menu = new ContextMenuStrip();
            menu.Items.Add(MenuItem("打开控制台", delegate { QueueOpenConsole(); }));
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(MenuItem("启动项目", delegate { QueuePost("/api/launcher/start", "启动项目"); }));
            menu.Items.Add(MenuItem("停止项目", delegate { QueuePost("/api/launcher/stop", "停止项目"); }));
            menu.Items.Add(MenuItem("重启项目", delegate { QueuePost("/api/launcher/restart", "重启项目"); }));
            menu.Items.Add(MenuItem("状态", delegate { QueueStatus(); }));
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(MenuItem("退出 Launcher", delegate { QueueExitLauncher(false); }));
            menu.Items.Add(MenuItem("停止全部", delegate { QueueExitLauncher(true); }));
            return menu;
        }

        private static ToolStripMenuItem MenuItem(string text, EventHandler handler)
        {
            var item = new ToolStripMenuItem(text);
            item.Click += handler;
            return item;
        }

        private void BootstrapLauncherBackend()
        {
            try
            {
                RunPythonBridge(projectDir, "bootstrap", true, true);
                ShowInfo("Launcher 已在托盘后台运行。");
            }
            catch (Exception ex)
            {
                ShowWarning("Launcher 后台启动失败：" + ShortMessage(ex.Message));
            }
        }

        private void QueueOpenConsole()
        {
            ThreadPool.QueueUserWorkItem(
                delegate
                {
                    try
                    {
                        RunPythonBridge(projectDir, "launcher", false, false);
                    }
                    catch (Exception ex)
                    {
                        ShowWarning("打开控制台失败：" + ShortMessage(ex.Message));
                    }
                }
            );
        }

        private void QueuePost(string path, string label)
        {
            ThreadPool.QueueUserWorkItem(
                delegate
                {
                    try
                    {
                        EnsureLauncherBackend();
                        PostLauncher(path);
                        ShowInfo(label + "请求已发送。");
                    }
                    catch (WebException ex)
                    {
                        ShowWarning(label + "失败：" + ShortMessage(ReadWebException(ex)));
                    }
                    catch (Exception ex)
                    {
                        ShowWarning(label + "失败：" + ShortMessage(ex.Message));
                    }
                }
            );
        }

        private void QueueStatus()
        {
            ThreadPool.QueueUserWorkItem(
                delegate
                {
                    try
                    {
                        EnsureLauncherBackend();
                        string body = GetLauncher("/api/launcher/status");
                        string overall = ExtractJsonString(body, "overallState");
                        string observed = ExtractJsonString(body, "observedState");
                        string consistency = ExtractJsonString(body, "lifecycleConsistency");
                        ShowInfo("状态：" + Fallback(overall, "unknown") + " / " + Fallback(observed, "unknown") + " / " + Fallback(consistency, "unknown"));
                    }
                    catch (Exception ex)
                    {
                        ShowWarning("读取状态失败：" + ShortMessage(ex.Message));
                    }
                }
            );
        }

        private void QueueExitLauncher(bool stopAll)
        {
            ThreadPool.QueueUserWorkItem(
                delegate
                {
                    try
                    {
                        if (stopAll)
                        {
                            EnsureLauncherBackend();
                            PostLauncher("/api/launcher/force-stop");
                            Thread.Sleep(1500);
                        }
                        RunPythonBridge(projectDir, "stop-launcher", true, false);
                    }
                    catch (Exception ex)
                    {
                        WriteFailure(projectDir, ex.ToString());
                    }
                    finally
                    {
                        RequestExit();
                    }
                }
            );
        }

        private void RequestExit()
        {
            uiContext.Post(
                delegate
                {
                    ExitThread();
                },
                null
            );
        }

        private void EnsureLauncherBackend()
        {
            if (LauncherHealthy())
            {
                return;
            }
            RunPythonBridge(projectDir, "bootstrap", true, true);
        }

        private bool LauncherHealthy()
        {
            try
            {
                GetLauncher("/api/health");
                return true;
            }
            catch
            {
                return false;
            }
        }

        private void PostLauncher(string path)
        {
            var request = (HttpWebRequest)WebRequest.Create(launcherUrl + path);
            request.Method = "POST";
            request.ContentLength = 0;
            using (var response = (HttpWebResponse)request.GetResponse())
            {
                if ((int)response.StatusCode >= 400)
                {
                    throw new InvalidOperationException("HTTP " + ((int)response.StatusCode).ToString());
                }
            }
        }

        private string GetLauncher(string path)
        {
            var request = (HttpWebRequest)WebRequest.Create(launcherUrl + path);
            request.Method = "GET";
            using (var response = (HttpWebResponse)request.GetResponse())
            using (var stream = response.GetResponseStream())
            using (var reader = new StreamReader(stream))
            {
                return reader.ReadToEnd();
            }
        }

        private void ShowInfo(string message)
        {
            ShowBalloon("Vibelution", message, ToolTipIcon.Info);
        }

        private void ShowWarning(string message)
        {
            ShowBalloon("Vibelution", message, ToolTipIcon.Warning);
        }

        private void ShowBalloon(string title, string message, ToolTipIcon icon)
        {
            uiContext.Post(
                delegate
                {
                    try
                    {
                        notifyIcon.BalloonTipTitle = title;
                        notifyIcon.BalloonTipText = message;
                        notifyIcon.BalloonTipIcon = icon;
                        notifyIcon.ShowBalloonTip(3000);
                    }
                    catch
                    {
                    }
                },
                null
            );
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                notifyIcon.Visible = false;
                notifyIcon.Dispose();
            }
            base.Dispose(disposing);
        }
    }

    private static ParsedArgs ParseArgs(string[] args)
    {
        var forwardedArgs = new List<string>();
        string projectDir = "";
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
        return new ParsedArgs
        {
            ProjectDir = Path.GetFullPath(projectDir),
            ForwardedArgs = forwardedArgs
        };
    }

    private static int RunLegacyScriptAction(string projectDir, List<string> forwardedArgs)
    {
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

    private static void RunPythonBridge(string projectDir, string action, bool noBrowser, bool outputJson)
    {
        string bridgePath = Path.Combine(projectDir, "scripts", "vibelution_desktop_entry.py");
        if (!File.Exists(bridgePath))
        {
            throw new FileNotFoundException("Desktop entry Python bridge was not found.", bridgePath);
        }

        string pythonPath = ResolvePython(projectDir, true);
        var arguments = new List<string>
        {
            Quote(bridgePath),
            "--action",
            action,
            "--python-exe",
            Quote(ResolvePython(projectDir, false))
        };
        if (outputJson)
        {
            arguments.Add("--output");
            arguments.Add("json");
        }
        if (noBrowser)
        {
            arguments.Add("--no-browser");
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = pythonPath,
            Arguments = string.Join(" ", arguments.ToArray()),
            WorkingDirectory = projectDir,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };

        using (Process process = Process.Start(startInfo))
        {
            if (process == null)
            {
                throw new InvalidOperationException("Failed to start desktop entry Python bridge.");
            }
            string stdout = process.StandardOutput.ReadToEnd();
            string stderr = process.StandardError.ReadToEnd();
            if (!process.WaitForExit(45000))
            {
                try { process.Kill(); } catch { }
                throw new TimeoutException("Desktop entry Python bridge timed out.");
            }
            if (process.ExitCode != 0)
            {
                throw new InvalidOperationException("Desktop entry Python bridge failed: " + ShortMessage(stderr + " " + stdout));
            }
        }
    }

    private static string ResolvePython(string projectDir, bool consolePython)
    {
        string scriptsDir = Path.Combine(projectDir, ".venv", "Scripts");
        string preferred = Path.Combine(scriptsDir, consolePython ? "python.exe" : "pythonw.exe");
        if (File.Exists(preferred))
        {
            return preferred;
        }
        string fallback = Path.Combine(scriptsDir, "python.exe");
        if (File.Exists(fallback))
        {
            return fallback;
        }
        return "python.exe";
    }

    private static int LauncherControlPort(string projectDir)
    {
        string envValue = Environment.GetEnvironmentVariable("VIBELUTION_LAUNCHER_PORT");
        int envPort;
        if (int.TryParse(envValue, out envPort) && envPort > 0 && envPort < 65536)
        {
            return envPort;
        }
        return 8765;
    }

    private static Icon LoadTrayIcon(string projectDir)
    {
        string iconPath = Path.Combine(projectDir, "assets", "icons", "vibelution.ico");
        if (File.Exists(iconPath))
        {
            return new Icon(iconPath);
        }
        return SystemIcons.Application;
    }

    private static string ExtractJsonString(string json, string key)
    {
        if (string.IsNullOrEmpty(json))
        {
            return "";
        }
        var match = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*\"(?<value>[^\"]*)\"");
        return match.Success ? match.Groups["value"].Value : "";
    }

    private static string ReadWebException(WebException ex)
    {
        try
        {
            if (ex.Response == null)
            {
                return ex.Message;
            }
            using (var stream = ex.Response.GetResponseStream())
            using (var reader = new StreamReader(stream))
            {
                return reader.ReadToEnd();
            }
        }
        catch
        {
            return ex.Message;
        }
    }

    private static string Fallback(string value, string fallback)
    {
        return string.IsNullOrWhiteSpace(value) ? fallback : value;
    }

    private static string ShortMessage(string value)
    {
        string text = (value ?? "").Replace("\r", " ").Replace("\n", " ").Trim();
        return text.Length > 220 ? text.Substring(0, 220) + "..." : text;
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
