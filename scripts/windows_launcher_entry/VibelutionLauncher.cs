using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
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
            string action = ResolveAction(parsed.ForwardedArgs);
            if (!action.Equals("launcher", StringComparison.OrdinalIgnoreCase))
            {
                return RunNativeAction(projectDir, parsed.ForwardedArgs);
            }

            bool created;
            bool waitForRestart = Environment.GetEnvironmentVariable("VIBELUTION_TRAY_RESTART_WAIT") == "1";
            using (var mutex = new Mutex(true, "Global\\Vibelution.Launcher.Tray", out created))
            {
                if (!created && waitForRestart)
                {
                    try
                    {
                        created = mutex.WaitOne(8000, false);
                    }
                    catch (AbandonedMutexException)
                    {
                        created = true;
                    }
                }
                if (!created || ElectronOwnsDesktopTray(projectDir))
                {
                    if (!created && !waitForRestart && !ElectronOwnsDesktopTray(projectDir) && parsed.FromShortcut)
                    {
                        return HandleSecondaryTrayLaunch(projectDir);
                    }
                    return 0;
                }

                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new TrayApplicationContext(projectDir, parsed.FromShortcut));
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
        public bool FromShortcut;
    }

    private sealed class TrayApplicationContext : ApplicationContext
    {
        private readonly string projectDir;
        private readonly bool fromShortcut;
        private readonly string launcherUrl;
        private readonly NotifyIcon notifyIcon;
        private readonly SynchronizationContext uiContext;
        private readonly FileSystemWatcher ownerWatcher;

        public TrayApplicationContext(string projectDir, bool fromShortcut)
        {
            this.projectDir = projectDir;
            this.fromShortcut = fromShortcut;
            this.launcherUrl = "http://127.0.0.1:" + LauncherControlPort(projectDir).ToString();
            this.uiContext = SynchronizationContext.Current ?? new WindowsFormsSynchronizationContext();
            this.notifyIcon = new NotifyIcon();
            this.notifyIcon.Text = "Vibelution Launcher";
            this.notifyIcon.Icon = LoadTrayIcon(projectDir);
            this.notifyIcon.ContextMenuStrip = BuildMenu();
            this.notifyIcon.Visible = true;
            this.notifyIcon.DoubleClick += delegate { QueueOpenConsole(); };
            this.ownerWatcher = WatchElectronTrayOwner();
            ThreadPool.QueueUserWorkItem(delegate { BootstrapLauncherBackend(); });
        }

        private ContextMenuStrip BuildMenu()
        {
            var menu = new ContextMenuStrip();
            menu.Items.Add(MenuItem("打开控制台", delegate { QueueOpenConsole(); }));
            var freshnessItem = DisabledMenuItem("Launcher 版本未知");
            menu.Items.Add(freshnessItem);
            menu.Items.Add(MenuItem("重启 Launcher", delegate { QueueRestartLauncher(); }));
            menu.Opening += delegate { QueueRefreshFreshnessItem(freshnessItem); };
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(BranchActionMenu("启动", "start"));
            menu.Items.Add(BranchActionMenu("停止", "stop"));
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(MenuItem("退出 Launcher", delegate { QueueExitLauncher(false); }));
            menu.Items.Add(MenuItem("停止全部", delegate { QueueExitLauncher(true); }));
            return menu;
        }

        private ToolStripMenuItem BranchActionMenu(string label, string operation)
        {
            var item = new ToolStripMenuItem(label);
            item.DropDownOpening += delegate { QueuePopulateBranchActionMenu(item, operation); };
            item.DropDownItems.Add(DisabledMenuItem(operation == "stop" ? "没有正在运行的实例" : "没有可启动的实例"));
            return item;
        }

        private void QueuePopulateBranchActionMenu(ToolStripMenuItem item, string operation)
        {
            item.DropDownItems.Clear();
            item.DropDownItems.Add(DisabledMenuItem("正在读取…"));
            ThreadPool.QueueUserWorkItem(
                delegate
                {
                    List<BranchInstanceItem> matched = null;
                    string placeholder = null;
                    try
                    {
                        if (!LauncherBackendHealthy(projectDir))
                        {
                            placeholder = "Launcher 后端未就绪";
                        }
                        else
                        {
                            matched = new List<BranchInstanceItem>();
                            foreach (var inst in ParseBranchInstances(
                                RequestLauncherStatic(projectDir, "/api/launcher/branch-instances", "GET")
                            ))
                            {
                                bool include = operation == "stop" ? inst.Alive : inst.Startable;
                                if (include)
                                {
                                    matched.Add(inst);
                                }
                            }
                            if (matched.Count == 0)
                            {
                                placeholder = operation == "stop" ? "没有正在运行的实例" : "没有可启动的实例";
                                matched = null;
                            }
                        }
                    }
                    catch
                    {
                        placeholder = "无法读取分支列表";
                        matched = null;
                    }

                    uiContext.Post(
                        delegate
                        {
                            try
                            {
                                item.DropDownItems.Clear();
                                if (!string.IsNullOrEmpty(placeholder))
                                {
                                    item.DropDownItems.Add(DisabledMenuItem(placeholder));
                                    return;
                                }
                                foreach (var inst in matched)
                                {
                                    var child = new ToolStripMenuItem(inst.Label);
                                    string instanceId = inst.Id;
                                    string instanceLabel = inst.Label;
                                    child.Click += delegate { QueueInstanceLifecycle(operation, instanceId, instanceLabel); };
                                    item.DropDownItems.Add(child);
                                }
                            }
                            catch
                            {
                            }
                        },
                        null
                    );
                }
            );
        }

        private void QueueInstanceLifecycle(string operation, string instanceId, string label)
        {
            string actionLabel = (operation == "stop" ? "停止 " : "启动 ") + label;
            ThreadPool.QueueUserWorkItem(
                delegate
                {
                    try
                    {
                        EnsureLauncherBackend();
                        PostLauncher(
                            "/api/launcher/branch-instances/" + operation,
                            "{\"instanceId\":" + Quote(instanceId) + "}"
                        );
                        ShowInfo(actionLabel + "请求已发送。");
                    }
                    catch (WebException ex)
                    {
                        ShowWarning(actionLabel + "失败：" + ShortMessage(ReadWebException(ex)));
                    }
                    catch (Exception ex)
                    {
                        ShowWarning(actionLabel + "失败：" + ShortMessage(ex.Message));
                    }
                }
            );
        }

        private static ToolStripMenuItem DisabledMenuItem(string text)
        {
            var item = new ToolStripMenuItem(text);
            item.Enabled = false;
            return item;
        }

        private sealed class BranchInstanceItem
        {
            public string Id;
            public string Label;
            public bool Alive;
            public bool Startable;
        }

        private static List<BranchInstanceItem> ParseBranchInstances(string json)
        {
            var items = new List<BranchInstanceItem>();
            if (string.IsNullOrEmpty(json))
            {
                return items;
            }
            foreach (Match match in Regex.Matches(json, "(?:\\{|,)\\s*\"id\"\\s*:\\s*\"(?<id>[^\"]+)\""))
            {
                int start = Math.Max(0, match.Index - 8);
                int length = Math.Min(json.Length - start, 1200);
                string chunk = json.Substring(start, length);
                string id = match.Groups["id"].Value;
                if (string.IsNullOrEmpty(id))
                {
                    continue;
                }
                string kind = ExtractJsonString(chunk, "kind");
                bool alive = ExtractJsonBool(chunk, "alive");
                bool checkedOut = ExtractJsonBool(chunk, "checkedOut");
                string shortName = ExtractJsonString(chunk, "shortName");
                string branch = ExtractJsonString(chunk, "branch");
                items.Add(new BranchInstanceItem
                {
                    Id = id,
                    Label = FirstNonEmpty(shortName, branch, id),
                    Alive = alive,
                    Startable = checkedOut && !alive && kind != "retired" && kind != "local_branch"
                });
            }
            return items;
        }

        private static bool ExtractJsonBool(string json, string key)
        {
            var match = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*(true|false)", RegexOptions.IgnoreCase);
            return match.Success && match.Groups[1].Value.Equals("true", StringComparison.OrdinalIgnoreCase);
        }

        private static string FirstNonEmpty(params string[] values)
        {
            foreach (string value in values)
            {
                if (!string.IsNullOrWhiteSpace(value))
                {
                    return value;
                }
            }
            return "";
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
                LaunchCurrentElectronMain(projectDir, "open", false);
                if (!fromShortcut)
                {
                    ShowInfo("Launcher 已在托盘后台运行。");
                }
            }
            catch (Exception ex)
            {
                if (!fromShortcut)
                {
                    ShowWarning("Launcher 后台启动失败：" + ShortMessage(ex.Message));
                }
                else
                {
                    WriteNativeEntryLog(projectDir, "native_action.bootstrap_failed", ShortStaticMessage(ex.Message));
                }
            }
        }

        private void QueueOpenConsole()
        {
            ThreadPool.QueueUserWorkItem(
                delegate
                {
                    try
                    {
                        LaunchCurrentElectronMain(projectDir, "open", false);
                    }
                    catch (Exception ex)
                    {
                        ShowWarning("打开控制台失败：" + ShortMessage(ex.Message));
                    }
                }
            );
        }

        private void QueueRefreshFreshnessItem(ToolStripMenuItem item)
        {
            ThreadPool.QueueUserWorkItem(
                delegate
                {
                    string nextLabel = "Launcher 版本未知";
                    try
                    {
                        if (LauncherBackendHealthy(projectDir))
                        {
                            string body = RequestLauncherStatic(projectDir, "/api/launcher/freshness", "GET");
                            string label = ExtractJsonString(body, "label");
                            if (!string.IsNullOrWhiteSpace(label))
                            {
                                nextLabel = label;
                            }
                        }
                    }
                    catch
                    {
                    }

                    uiContext.Post(
                        delegate
                        {
                            try
                            {
                                item.Text = nextLabel;
                            }
                            catch
                            {
                            }
                        },
                        null
                    );
                }
            );
        }

        private void QueueRestartLauncher()
        {
            ThreadPool.QueueUserWorkItem(
                delegate
                {
                    try
                    {
                        EnsureLauncherBackend();
                        ShowInfo("正在停止全部托管进程并重启 Launcher…");
                        PostLauncher("/api/launcher/force-stop");
                        Thread.Sleep(1500);
                        string exe = Application.ExecutablePath;
                        string args = "--action launcher --project " + Quote(projectDir);
                        var start = new ProcessStartInfo();
                        start.FileName = exe;
                        start.Arguments = args;
                        start.WorkingDirectory = projectDir;
                        start.UseShellExecute = false;
                        start.CreateNoWindow = true;
                        start.Environment["VIBELUTION_TRAY_RESTART_WAIT"] = "1";
                        Process.Start(start);
                    }
                    catch (Exception ex)
                    {
                        ShowWarning("重启 Launcher 失败：" + ShortMessage(ex.Message));
                        return;
                    }
                    QueueExitLauncher(false);
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

        private void QueueRebuildAndStart()
        {
            ThreadPool.QueueUserWorkItem(
                delegate
                {
                    try
                    {
                        EnsureLauncherBackend();
                        // Single accept toast (avoid double balloon spam). Outcome toast after poll.
                        // Rebuild runs inside runtime-manager after accept; keep API timeout short.
                        PostLauncher("/api/launcher/rebuild-and-start");
                        ShowInfo("重建并启动已受理，正在后台构建/拉起…");
                        string lastFailure = WaitForRebuildOutcome(90000);
                        if (!string.IsNullOrEmpty(lastFailure))
                        {
                            ShowWarning("重建/启动失败：" + ShortMessage(lastFailure));
                        }
                        else
                        {
                            ShowInfo("重建并启动已完成（或仍在收尾中）。");
                        }
                    }
                    catch (WebException ex)
                    {
                        string detail = ShortMessage(ReadWebException(ex));
                        if (detail.IndexOf("active_work", StringComparison.OrdinalIgnoreCase) >= 0
                            || detail.IndexOf("进行中的任务", StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            ShowWarning("有进行中的任务，无法重建并重启。请等待任务完成或先停止任务。");
                        }
                        else
                        {
                            ShowWarning("重建并启动失败：" + detail);
                        }
                    }
                    catch (Exception ex)
                    {
                        ShowWarning("重建并启动失败：" + ShortMessage(ex.Message));
                    }
                }
            );
        }

        private string WaitForRebuildOutcome(int timeoutMs)
        {
            // Capture baseline before the rebuild request so a still-open old workbench
            // is not treated as success (preflight can fail without closing).
            string baselineStatus = "";
            try
            {
                baselineStatus = GetLauncher("/api/launcher/status");
            }
            catch
            {
            }
            string baselineErrorAt = ExtractJsonString(baselineStatus, "lastErrorAt");
            string baselineVersion = ExtractJsonString(baselineStatus, "stateVersion");
            int waited = 0;
            string lastFailure = "";
            bool sawVersionAdvance = false;
            while (waited < timeoutMs)
            {
                try
                {
                    string body = GetLauncher("/api/launcher/status");
                    string overall = ExtractJsonString(body, "overallState").ToLowerInvariant();
                    string observed = ExtractJsonString(body, "observedState").ToLowerInvariant();
                    string phase = ExtractJsonString(body, "phase").ToLowerInvariant();
                    string failure = ExtractJsonString(body, "failureMessage");
                    string lastErrorMessage = ExtractJsonString(body, "lastErrorMessage");
                    string lastErrorAt = ExtractJsonString(body, "lastErrorAt");
                    string stateVersion = ExtractJsonString(body, "stateVersion");
                    if (!string.IsNullOrEmpty(stateVersion)
                        && !string.IsNullOrEmpty(baselineVersion)
                        && !string.Equals(stateVersion, baselineVersion, StringComparison.Ordinal))
                    {
                        sawVersionAdvance = true;
                    }
                    string terminalFailure = !string.IsNullOrEmpty(failure) ? failure : lastErrorMessage;
                    bool newLifecycleError = !string.IsNullOrEmpty(lastErrorMessage)
                        && !string.Equals(lastErrorAt ?? "", baselineErrorAt ?? "", StringComparison.Ordinal);
                    if (newLifecycleError || (sawVersionAdvance && !string.IsNullOrEmpty(terminalFailure)))
                    {
                        return ShortMessage(terminalFailure);
                    }
                    if (!string.IsNullOrEmpty(terminalFailure))
                    {
                        lastFailure = terminalFailure;
                    }
                    if (overall == "failed" || phase == "failed")
                    {
                        if (!string.IsNullOrEmpty(terminalFailure))
                        {
                            return ShortMessage(terminalFailure);
                        }
                    }
                    // Success only after this rebuild advanced state and the workbench is fully open.
                    // Never treat a pre-existing open session as rebuild success.
                    if (sawVersionAdvance
                        && (overall == "ready" || observed == "open")
                        && phase != "failed"
                        && phase != "opening"
                        && string.IsNullOrEmpty(lastErrorMessage)
                        && string.IsNullOrEmpty(failure))
                    {
                        return "";
                    }
                }
                catch
                {
                    // keep polling while backend restarts
                }
                Thread.Sleep(2000);
                waited += 2000;
            }
            if (!string.IsNullOrEmpty(lastFailure))
            {
                return ShortMessage(lastFailure);
            }
            return "重建/启动超时：未看到成功完成的状态变更。";
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
            EnsureFreshLauncherBackend(projectDir);
        }

        private bool LauncherHealthy()
        {
            return LauncherBackendHealthy(projectDir);
        }

        private void PostLauncher(string path)
        {
            PostLauncher(path, null);
        }

        private void PostLauncher(string path, string jsonBody)
        {
            var request = (HttpWebRequest)WebRequest.Create(launcherUrl + path);
            request.Method = "POST";
            if (string.IsNullOrEmpty(jsonBody))
            {
                request.ContentLength = 0;
            }
            else
            {
                byte[] payload = Encoding.UTF8.GetBytes(jsonBody);
                request.ContentType = "application/json; charset=utf-8";
                request.ContentLength = payload.Length;
                using (var stream = request.GetRequestStream())
                {
                    stream.Write(payload, 0, payload.Length);
                }
            }
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
            request.Timeout = 15000;
            request.ReadWriteTimeout = 15000;
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
                if (ownerWatcher != null)
                {
                    ownerWatcher.EnableRaisingEvents = false;
                    ownerWatcher.Dispose();
                }
                notifyIcon.Visible = false;
                notifyIcon.Dispose();
            }
            base.Dispose(disposing);
        }

        private FileSystemWatcher WatchElectronTrayOwner()
        {
            string canonical = ResolveCanonicalDesktopShellOwnerPath(projectDir);
            string ownerDir = !string.IsNullOrEmpty(canonical)
                ? Path.GetDirectoryName(canonical)
                : Path.Combine(projectDir, ".runtime", "launcher");
            if (!string.IsNullOrEmpty(canonical))
            {
                Directory.CreateDirectory(ownerDir);
            }
            else if (!Directory.Exists(ownerDir))
            {
                return null;
            }
            var watcher = new FileSystemWatcher(ownerDir, "desktop_shell_owner.json");
            watcher.NotifyFilter = NotifyFilters.FileName | NotifyFilters.LastWrite | NotifyFilters.CreationTime;
            FileSystemEventHandler onOwnerChanged = delegate { YieldTrayIfElectronOwns(); };
            watcher.Created += onOwnerChanged;
            watcher.Changed += onOwnerChanged;
            watcher.EnableRaisingEvents = true;
            return watcher;
        }

        private void YieldTrayIfElectronOwns()
        {
            if (!ElectronOwnsDesktopTray(projectDir))
            {
                return;
            }
            uiContext.Post(
                delegate
                {
                    try
                    {
                        notifyIcon.Visible = false;
                    }
                    catch
                    {
                    }
                    ExitThread();
                },
                null
            );
        }
    }

    private static string ResolveProjectsHome()
    {
        string overrideHome = Environment.GetEnvironmentVariable("VIBELUTION_PROJECTS_HOME");
        if (!string.IsNullOrWhiteSpace(overrideHome))
        {
            return Path.GetFullPath(overrideHome.Trim());
        }
        string localAppData = Environment.GetEnvironmentVariable("LOCALAPPDATA");
        if (string.IsNullOrWhiteSpace(localAppData))
        {
            localAppData = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "AppData", "Local");
        }
        return Path.Combine(localAppData, "Vibelution", "projects");
    }

    private static string ReadProjectId(string projectDir)
    {
        try
        {
            string identityPath = Path.Combine(projectDir, ".vibelution", "project.json");
            if (!File.Exists(identityPath))
            {
                return "";
            }
            string text = File.ReadAllText(identityPath);
            Match match = Regex.Match(text, "\"projectId\"\\s*:\\s*\"([^\"]+)\"");
            return match.Success ? match.Groups[1].Value.Trim().ToLowerInvariant() : "";
        }
        catch
        {
            return "";
        }
    }

    private static string InstanceIdForProject(string projectDir)
    {
        string resolved = Path.GetFullPath(projectDir.Trim());
        string key = Environment.OSVersion.Platform == PlatformID.Win32NT ? resolved.ToLowerInvariant() : resolved;
        uint digest = 2166136261;
        unchecked
        {
            foreach (byte value in Encoding.UTF8.GetBytes(key))
            {
                digest ^= value;
                digest *= 16777619;
            }
        }
        return digest.ToString("x8");
    }

    private static string ResolveCanonicalDesktopShellOwnerPath(string projectDir)
    {
        string projectId = ReadProjectId(projectDir);
        if (string.IsNullOrEmpty(projectId))
        {
            return "";
        }
        return Path.Combine(
            ResolveProjectsHome(),
            projectId,
            "instances",
            InstanceIdForProject(projectDir),
            "runtime",
            "launcher",
            "desktop_shell_owner.json"
        );
    }

    private static string ResolveDesktopShellOwnerPath(string projectDir)
    {
        string canonical = ResolveCanonicalDesktopShellOwnerPath(projectDir);
        if (!string.IsNullOrEmpty(canonical) && File.Exists(canonical))
        {
            return canonical;
        }
        string checkout = Path.Combine(projectDir, ".runtime", "launcher", "desktop_shell_owner.json");
        if (File.Exists(checkout))
        {
            return checkout;
        }
        return string.IsNullOrEmpty(canonical) ? checkout : canonical;
    }

    private static bool ElectronOwnsDesktopTray(string projectDir)
    {
        try
        {
            string path = ResolveDesktopShellOwnerPath(projectDir);
            if (string.IsNullOrEmpty(path) || !File.Exists(path))
            {
                return false;
            }
            string text = File.ReadAllText(path);
            if (text.IndexOf("\"electron\"", StringComparison.OrdinalIgnoreCase) < 0)
            {
                return false;
            }
            Match pidMatch = Regex.Match(text, "\"pid\"\\s*:\\s*(\\d+)");
            int pid;
            if (!pidMatch.Success || !int.TryParse(pidMatch.Groups[1].Value, out pid) || pid <= 0)
            {
                return false;
            }
            Match createTimeMatch = Regex.Match(text, "\"createTime\"\\s*:\\s*([0-9]+(?:\\.[0-9]+)?)");
            Match exeMatch = Regex.Match(text, "\"executable\"\\s*:\\s*\"([^\"]*)\"");
            double expectedCreateTime = 0;
            if (createTimeMatch.Success)
            {
                double.TryParse(createTimeMatch.Groups[1].Value, out expectedCreateTime);
            }
            string expectedExe = exeMatch.Success ? exeMatch.Groups[1].Value.Trim() : "";
            Process process = Process.GetProcessById(pid);
            if (process == null || process.HasExited)
            {
                return false;
            }
            if (expectedCreateTime <= 0 || string.IsNullOrEmpty(expectedExe))
            {
                return true;
            }
            DateTime epoch = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);
            double actualCreateTime = (process.StartTime.ToUniversalTime() - epoch).TotalSeconds;
            if (Math.Abs(actualCreateTime - expectedCreateTime) > 2.0)
            {
                return false;
            }
            string actualExe = "";
            try
            {
                actualExe = process.MainModule != null ? process.MainModule.FileName : "";
            }
            catch
            {
                return true;
            }
            return !string.IsNullOrEmpty(actualExe)
                && string.Equals(actualExe, expectedExe, StringComparison.OrdinalIgnoreCase);
        }
        catch (ArgumentException)
        {
            return false;
        }
        catch (InvalidOperationException)
        {
            return false;
        }
        catch (Exception)
        {
            return false;
        }
    }

    private static int HandleSecondaryTrayLaunch(string projectDir)
    {
        try
        {
            LaunchCurrentElectronMain(projectDir, "open", false);
            WriteNativeEntryLog(projectDir, "native_action.secondary_launch", "action=open_console");
        }
        catch (Exception ex)
        {
            WriteFailure(projectDir, ex.ToString());
            return 1;
        }
        return 0;
    }

    private static void EnsureFreshLauncherBackend(string projectDir)
    {
        bool healthy = LauncherBackendHealthy(projectDir);
        bool fresh = healthy && LauncherBackendFresh(projectDir);
        if (fresh)
        {
            return;
        }
        if (healthy)
        {
            try
            {
                RunPythonBridge(projectDir, "stop-launcher", true, false);
                Thread.Sleep(500);
            }
            catch
            {
            }
        }
        RunPythonBridge(projectDir, "bootstrap", true, true);
    }

    private static bool LauncherBackendHealthy(string projectDir)
    {
        try
        {
            RequestLauncherStatic(projectDir, "/api/health", "GET");
            return true;
        }
        catch
        {
            return false;
        }
    }

    private static bool LauncherBackendFresh(string projectDir)
    {
        try
        {
            string body = RequestLauncherStatic(projectDir, "/api/launcher/freshness", "GET");
            if (body.IndexOf("\"current\":true", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                return true;
            }
            if (body.IndexOf("\"current\":false", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                return false;
            }
            return false;
        }
        catch
        {
            return false;
        }
    }

    private static string RequestLauncherStatic(string projectDir, string path, string method)
    {
        string url = "http://127.0.0.1:" + LauncherControlPort(projectDir).ToString() + path;
        var request = (HttpWebRequest)WebRequest.Create(url);
        request.Method = method;
        request.Timeout = 15000;
        request.ReadWriteTimeout = 15000;
        request.Headers["X-Vibelution-Launcher-Trigger"] = "native_entry";
        if (method == "POST")
        {
            request.ContentLength = 0;
        }
        using (var response = (HttpWebResponse)request.GetResponse())
        using (var stream = response.GetResponseStream())
        using (var reader = new StreamReader(stream))
        {
            return reader.ReadToEnd();
        }
    }

    private static string ShortStaticMessage(string message)
    {
        string text = (message ?? "").Trim();
        if (text.Length <= 180)
        {
            return text;
        }
        return text.Substring(0, 177) + "...";
    }

    private static ParsedArgs ParseArgs(string[] args)
    {
        var forwardedArgs = new List<string>();
        string projectDir = "";
        bool fromShortcut = false;
        for (int index = 0; index < args.Length; index++)
        {
            string arg = args[index] ?? "";
            if (arg.Equals("--project", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
            {
                projectDir = args[++index];
                continue;
            }
            if (arg.Equals("--from-shortcut", StringComparison.OrdinalIgnoreCase))
            {
                fromShortcut = true;
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
            ForwardedArgs = forwardedArgs,
            FromShortcut = fromShortcut
        };
    }

    private static string ResolveAction(List<string> forwardedArgs)
    {
        string action = "launcher";
        for (int index = 0; index < forwardedArgs.Count; index++)
        {
            string value = (forwardedArgs[index] ?? "").Trim();
            string lowered = value.ToLowerInvariant();
            if ((lowered == "-action" || lowered == "--action") && index + 1 < forwardedArgs.Count)
            {
                return (forwardedArgs[index + 1] ?? "launcher").Trim().ToLowerInvariant();
            }
            if (lowered.StartsWith("-action:") || lowered.StartsWith("-action="))
            {
                return lowered.Substring(8).Trim();
            }
            if (lowered.StartsWith("--action:") || lowered.StartsWith("--action="))
            {
                return lowered.Substring(9).Trim();
            }
            if (!value.StartsWith("-") && action == "launcher")
            {
                action = lowered;
            }
        }
        return action;
    }

    private static int RunNativeAction(string projectDir, List<string> forwardedArgs)
    {
        string action = ResolveAction(forwardedArgs);
        if (action == "open")
        {
            if (ForwardOrLaunchElectron(projectDir, action, forwardedArgs))
            {
                WriteNativeEntryLog(projectDir, "native_action.electron_forwarded", "action=open");
                return 0;
            }
            WriteNativeEntryLog(projectDir, "native_action.electron_launch_failed", "action=open");
            return 1;
        }

        if (action != "toggle" && action != "start" && action != "stop" && action != "force-stop" && action != "close" && action != "restart" && action != "rebuild-and-start" && action != "status")
        {
            WriteNativeEntryLog(projectDir, "native_action.rejected", "action=" + ShortMessage(action));
            return 2;
        }

        // Electron main owns lifecycle commands. Launch the current checkout
        // shell (packaged if current, otherwise unpackaged Electron main).
        if (ForwardOrLaunchElectron(projectDir, action, forwardedArgs))
        {
            WriteNativeEntryLog(projectDir, "native_action.electron_forwarded", "action=" + action);
            return 0;
        }

        WriteNativeEntryLog(projectDir, "native_action.electron_launch_failed", "action=" + action);
        return 1;
    }

    private static bool ForwardOrLaunchElectron(string projectDir, string action, List<string> forwardedArgs)
    {
        bool openWorkbench = action == "open" || action == "start" || action == "restart" || action == "rebuild-and-start";
        try
        {
            LaunchCurrentElectronMain(projectDir, action, openWorkbench);
            return true;
        }
        catch (Exception ex)
        {
            WriteNativeEntryLog(projectDir, "native_action.electron_launch_failed", ShortStaticMessage(ex.Message));
            return false;
        }
    }

    private static string ResolveDesktopShellWorkspace(string projectDir)
    {
        string path = Path.GetFullPath(string.IsNullOrWhiteSpace(projectDir) ? "." : projectDir);
        string[] parts = path.Replace('/', Path.DirectorySeparatorChar).Split(Path.DirectorySeparatorChar);
        for (int index = 0; index < parts.Length; index++)
        {
            if (string.Equals(parts[index], ".worktrees", StringComparison.OrdinalIgnoreCase))
            {
                if (index == 0)
                {
                    return path;
                }
                return string.Join(Path.DirectorySeparatorChar.ToString(), parts, 0, index);
            }
        }
        return path;
    }

    private static void LaunchCurrentElectronMain(string projectDir, string thenLifecycle, bool openWorkbench)
    {
        RunPythonBridge(projectDir, "launch-desktop-shell", true, true, thenLifecycle, openWorkbench, 120000);
    }

    private static bool HasArgument(List<string> args, params string[] accepted)
    {
        foreach (string value in args)
        {
            foreach (string candidate in accepted)
            {
                if (string.Equals((value ?? "").Trim(), candidate, StringComparison.OrdinalIgnoreCase))
                {
                    return true;
                }
            }
        }
        return false;
    }

    private static string RequestLauncher(string projectDir, string path, string method)
    {
        string url = "http://127.0.0.1:" + LauncherControlPort(projectDir).ToString() + path;
        var request = (HttpWebRequest)WebRequest.Create(url);
        request.Method = method;
        request.Timeout = 15000;
        request.ReadWriteTimeout = 15000;
        request.Headers["X-Vibelution-Launcher-Trigger"] = "native_entry";
        if (method == "POST")
        {
            request.ContentLength = 0;
        }
        using (var response = (HttpWebResponse)request.GetResponse())
        using (var stream = response.GetResponseStream())
        using (var reader = new StreamReader(stream))
        {
            return reader.ReadToEnd();
        }
    }

    private static void RunPythonBridge(string projectDir, string action, bool noBrowser, bool outputJson)
    {
        RunPythonBridge(projectDir, action, noBrowser, outputJson, "", false, 45000);
    }

    private static void RunPythonBridge(
        string projectDir,
        string action,
        bool noBrowser,
        bool outputJson,
        string thenLifecycle,
        bool openWorkbench,
        int timeoutMs)
    {
        string requestedRoot = Path.GetFullPath(projectDir);
        string shellRoot = ResolveDesktopShellWorkspace(requestedRoot);
        string bridgePath = Path.Combine(shellRoot, "scripts", "vibelution_desktop_entry.py");
        if (!File.Exists(bridgePath))
        {
            throw new FileNotFoundException("Desktop entry Python bridge was not found.", bridgePath);
        }

        string pythonPath = ResolvePython(shellRoot, useNoConsole: true);
        var arguments = new List<string>
        {
            Quote(bridgePath),
            "--action",
            action,
            "--python-exe",
            Quote(ResolvePython(shellRoot, useNoConsole: false))
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
        if (string.Equals(action, "stop-launcher", StringComparison.OrdinalIgnoreCase)
            || string.Equals(action, "launch-desktop-shell", StringComparison.OrdinalIgnoreCase))
        {
            arguments.Add("--workspace");
            arguments.Add(Quote(
                string.Equals(action, "launch-desktop-shell", StringComparison.OrdinalIgnoreCase)
                    ? requestedRoot
                    : shellRoot));
        }
        if (string.Equals(action, "stop-launcher", StringComparison.OrdinalIgnoreCase))
        {
            arguments.Add("--use-state-owned-backend-pid");
        }
        if (!string.IsNullOrWhiteSpace(thenLifecycle))
        {
            arguments.Add("--then-lifecycle");
            arguments.Add(thenLifecycle);
        }
        if (openWorkbench)
        {
            arguments.Add("--open-workbench");
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = pythonPath,
            Arguments = string.Join(" ", arguments.ToArray()),
            WorkingDirectory = shellRoot,
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
            // Drain stdout/stderr asynchronously. ReadToEnd() before WaitForExit
            // deadlocks when a grandchild (Electron) inherits the redirected pipe.
            var stdout = new StringBuilder();
            var stderr = new StringBuilder();
            process.OutputDataReceived += (sender, e) => { if (e.Data != null) stdout.AppendLine(e.Data); };
            process.ErrorDataReceived += (sender, e) => { if (e.Data != null) stderr.AppendLine(e.Data); };
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            int waitMs = timeoutMs > 0 ? timeoutMs : 45000;
            if (!process.WaitForExit(waitMs))
            {
                try { process.Kill(); } catch { }
                try { process.WaitForExit(2000); } catch { }
                throw new TimeoutException("Desktop entry Python bridge timed out.");
            }
            process.WaitForExit();
            if (process.ExitCode != 0)
            {
                throw new InvalidOperationException("Desktop entry Python bridge failed: " + ShortMessage(stderr.ToString() + " " + stdout.ToString()));
            }
        }
    }

    private static string ResolvePython(string projectDir, bool useNoConsole)
    {
        string scriptsDir = Path.Combine(projectDir, ".venv", "Scripts");
        string preferred = Path.Combine(scriptsDir, useNoConsole ? "pythonw.exe" : "python.exe");
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
        WriteNativeEntryLog(projectDir, "native_entry.failed", ShortMessage(message));
    }

    private static void WriteNativeEntryLog(string projectDir, string eventName, string message)
    {
        try
        {
            string logDir = Path.Combine(projectDir, ".runtime", "launcher");
            Directory.CreateDirectory(logDir);
            string logPath = Path.Combine(logDir, "native-launcher-entry.log");
            File.AppendAllText(
                logPath,
                DateTimeOffset.Now.ToString("o") + " " + eventName + " " + ShortMessage(message) + Environment.NewLine
            );
        }
        catch
        {
        }
    }
}
