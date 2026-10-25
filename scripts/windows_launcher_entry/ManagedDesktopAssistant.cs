using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using Microsoft.Win32.SafeHandles;

// Bootstrap integrity only. Publication belongs to the existing Python package
// owner; this entry never searches a checkout, runs Python or repairs an install.
internal static class ManagedDesktopAssistant
{
    private const string Unavailable = "ASSISTANT_PACKAGE_UNAVAILABLE";
    private const uint Reparse = 0x400, DirectoryAttribute = 0x10;
    private static readonly UTF8Encoding Utf8 = new UTF8Encoding(false, true);
    private static readonly Regex Sha = new Regex("^[0-9a-f]{64}$");

    internal static bool IsRequested(string[] args)
    {
        foreach (string value in args)
            if ((value ?? "").Trim().Equals("--assistant", StringComparison.OrdinalIgnoreCase)
                || (value ?? "").Trim().StartsWith("--assistant=", StringComparison.OrdinalIgnoreCase)) return true;
        return false;
    }

    internal static int Run(string[] args)
    {
        try
        {
            string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (String.IsNullOrWhiteSpace(local)) throw new InvalidDataException(Unavailable);
            using (var launch = PrepareStart(args, Path.Combine(local, "Vibelution", "Launcher", "managed-desktop")))
            {
                launch.CheckMembers();
                using (Process child = Process.Start(launch.Info))
                    if (child == null) throw new InvalidDataException(Unavailable);
            }
            return 0;
        }
        catch (Exception ex)
        {
            // Do not run the project failure logger on this no-project branch.
            Console.Error.WriteLine(ex.Message == "ASSISTANT_MODE_CONFLICT" ? ex.Message : Unavailable);
            return 1;
        }
    }

    internal static ProcessStartInfo ResolveStartInfo(string[] args, string managedRoot)
    {
        using (var launch = PrepareStart(args, managedRoot)) return launch.Info;
    }

    // Hold admitted bytes and parent identities through OS process creation.
    // Recheck membership at handoff too. This is not an ACL or a promise against
    // a same-user writer adding files after handoff; the publisher never mutates
    // an installed version and this component is not publisher authentication.
    internal sealed class PreparedLaunch : IDisposable
    {
        internal readonly ProcessStartInfo Info;
        private readonly List<FileStream> held;
        private readonly string package;
        private readonly HashSet<string> members;
        internal PreparedLaunch(ProcessStartInfo info, List<FileStream> held, string package, HashSet<string> members)
        { Info = info; this.held = held; this.package = package; this.members = members; }
        internal void CheckMembers() { ExactTree(package, new HashSet<string>(members, StringComparer.OrdinalIgnoreCase), null); }
        public void Dispose() { for (int i = held.Count - 1; i >= 0; i--) held[i].Dispose(); held.Clear(); }
    }

    internal static PreparedLaunch PrepareStart(string[] args, string managedRoot)
    {
        bool assistant = false, hidden = false;
        foreach (string arg in args)
        {
            if (arg == "--assistant" && !assistant) assistant = true;
            else if ((arg == "--hidden" || arg == "--hidden-presentation") && !hidden) hidden = true;
            else throw new InvalidDataException("ASSISTANT_MODE_CONFLICT");
        }
        if (!assistant) throw new InvalidDataException("ASSISTANT_MODE_CONFLICT");
        var held = new List<FileStream>();
        try
        {
            string root = CanonicalRoot(managedRoot);
            HoldAncestors(root, held);
            var active = Json(ReadBytes(Child(root, "active.json"), 16 * 1024, held));
            Keys(active, "schemaVersion", "protocolVersion", "packageId", "exeSha256", "provenanceSha256");
            if (Number(active["schemaVersion"]) != 1 || Number(active["protocolVersion"]) != 1) Fail();
            string id = HashValue(active["packageId"]);
            string package = Child(root, "packages/" + id);
            held.Add(Open(Child(root, "packages"), true));
            held.Add(Open(package, true));
            byte[] bytes = ReadBytes(Child(package, "managed-package-catalog.json"), 16 * 1024 * 1024, held);
            if (Hash(bytes) != id) Fail();
            var catalog = Json(bytes);
            Keys(catalog, "schemaVersion", "files");
            if (Number(catalog["schemaVersion"]) != 1) Fail();
            var files = catalog["files"] as IList;
            if (files == null || files.Count < 4 || files.Count > 50000) Fail();
            var expected = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var hashes = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            long total = 0;
            foreach (object value in files)
            {
                var row = value as Dictionary<string, object>;
                Keys(row, "path", "size", "sha256");
                string relative = row["path"] as string;
                if (!Portable(relative) || relative.Equals("managed-package-catalog.json", StringComparison.OrdinalIgnoreCase)
                    || !expected.Add(relative)) Fail();
                long size = Number(row["size"]);
                if (size < 0 || size > 512L * 1024 * 1024) Fail();
                total += size;
                if (total > 4L * 1024 * 1024 * 1024) Fail();
                string wanted = HashValue(row["sha256"]);
                FileStream file = Open(Child(package, relative), false);
                held.Add(file);
                {
                    if (file.Length != size) Fail();
                    using (var sha = SHA256.Create())
                        if (Hex(sha.ComputeHash(file)) != wanted || file.Position != size) Fail();
                }
                hashes.Add(relative, wanted);
            }
            foreach (string required in new[] { "Vibelution.exe", "resources/app.asar",
                "resources/app.asar.unpacked/package-provenance.json", "resources/launcher-assistant/manifest.json" })
                if (!hashes.ContainsKey(required)) Fail();
            if (hashes["Vibelution.exe"] != HashValue(active["exeSha256"])
                || hashes["resources/app.asar.unpacked/package-provenance.json"] != HashValue(active["provenanceSha256"])) Fail();
            // Unlisted DLLs/code and junctions must not survive the same admission.
            expected.Add("managed-package-catalog.json");
            var members = new HashSet<string>(expected, StringComparer.OrdinalIgnoreCase);
            ExactTree(package, expected, held);
            var info = new ProcessStartInfo {
                FileName = PublicProcessPath(Child(package, "Vibelution.exe"), false, held),
                WorkingDirectory = PublicProcessPath(package, true, held),
                Arguments = "--assistant" + (hidden ? " --hidden-presentation" : ""),
                UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden
            };
            var keys = new List<string>();
            foreach (string key in info.EnvironmentVariables.Keys) keys.Add(key);
            foreach (string key in keys)
                if (Regex.IsMatch(key, "^(VIBELUTION_WORKSPACE_ROOT|VIBELUTION_PYTHON_PATH|PYTHON|PYTHONPATH|PYTHONHOME)$", RegexOptions.IgnoreCase))
                    info.EnvironmentVariables.Remove(key);
            return new PreparedLaunch(info, held, package, members);
        }
        catch { for (int i = held.Count - 1; i >= 0; i--) held[i].Dispose(); throw new InvalidDataException(Unavailable); }
    }

    private static void Fail() { throw new InvalidDataException(Unavailable); }
    private static long Number(object value)
    {
        if (!(value is int) && !(value is long)) Fail();
        return Convert.ToInt64(value);
    }
    private static string HashValue(object value)
    {
        var text = value as string;
        if (text == null || !Sha.IsMatch(text)) Fail();
        return text;
    }
    private static string Hex(byte[] bytes) { return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant(); }
    private static string Hash(byte[] bytes) { using (var sha = SHA256.Create()) return Hex(sha.ComputeHash(bytes)); }
    private static void Keys(Dictionary<string, object> value, params string[] keys)
    {
        if (value == null || value.Count != keys.Length) Fail();
        foreach (string key in keys) if (!value.ContainsKey(key)) Fail();
    }

    private static Dictionary<string, object> Json(byte[] bytes)
    {
        string text = Utf8.GetString(bytes);
        var json = new JavaScriptSerializer { MaxJsonLength = 16 * 1024 * 1024, RecursionLimit = 32 };
        // JavaScriptSerializer otherwise silently accepts duplicate decoded keys.
        var objects = new Stack<HashSet<string>>();
        for (int i = 0; i < text.Length; i++)
        {
            if (text[i] == '{') objects.Push(new HashSet<string>(StringComparer.Ordinal));
            else if (text[i] == '}') { if (objects.Count == 0) Fail(); objects.Pop(); }
            else if (text[i] == '"')
            {
                int start = i++;
                for (; i < text.Length && text[i] != '"'; i++) if (text[i] == '\\') i++;
                if (i >= text.Length) Fail();
                int next = i + 1;
                while (next < text.Length && Char.IsWhiteSpace(text[next])) next++;
                if (next < text.Length && text[next] == ':')
                {
                    string key = json.Deserialize<string>(text.Substring(start, i - start + 1));
                    if (objects.Count == 0 || !objects.Peek().Add(key)) Fail();
                }
            }
        }
        if (objects.Count != 0) Fail();
        return json.Deserialize<Dictionary<string, object>>(text);
    }

    private static bool Portable(string path)
    {
        if (String.IsNullOrEmpty(path) || path.Length > 4096) return false;
        foreach (string part in path.Split('/'))
        {
            if (part.Length == 0 || part == "." || part == ".." || part.EndsWith(".") || part.EndsWith(" ")) return false;
            foreach (char c in part) if (c < 32 || c == 127 || "<>:\"\\|?*".IndexOf(c) >= 0) return false;
            string device = part.Split('.')[0].TrimEnd(' ').Replace('¹', '1').Replace('²', '2').Replace('³', '3');
            if (Regex.IsMatch(device, "^(CON|PRN|AUX|NUL|CONIN\\$|CONOUT\\$|COM[1-9]|LPT[1-9])$", RegexOptions.IgnoreCase)) return false;
        }
        return true;
    }
    private static string Child(string root, string relative)
    {
        if (!Portable(relative)) { Fail(); }
        string current = root.TrimEnd('\\');
        string[] parts = relative.Split('/');
        for (int i = 0; i < parts.Length; i++)
        {
            current += "\\" + parts[i];
            uint attrs = GetFileAttributesW(current);
            if (attrs == UInt32.MaxValue || (attrs & Reparse) != 0 || (i < parts.Length - 1 && (attrs & DirectoryAttribute) == 0)) Fail();
        }
        return current;
    }
    private static string CanonicalRoot(string root)
    {
        var directory = new DirectoryInfo(Path.GetFullPath(root));
        for (var current = directory; current != null; current = current.Parent)
            if ((current.Attributes & FileAttributes.ReparsePoint) != 0) Fail();
        string namespaced = directory.FullName.StartsWith("\\\\") ? "\\\\?\\UNC\\" + directory.FullName.Substring(2) : "\\\\?\\" + directory.FullName;
        using (FileStream stream = Open(namespaced, true)) return FinalPath(stream.SafeFileHandle).TrimEnd('\\');
    }
    private static void HoldAncestors(string root, List<FileStream> held)
    {
        int prefix = root.StartsWith("\\\\?\\UNC\\", StringComparison.OrdinalIgnoreCase)
            ? root.IndexOf('\\', root.IndexOf('\\', 8) + 1) + 1 : 7;
        if (prefix < 7) Fail();
        held.Add(Open(root.Substring(0, prefix), true));
        for (int i = prefix; i < root.Length; i++)
            if (root[i] == '\\') held.Add(Open(root.Substring(0, i), true));
        held.Add(Open(root, true));
    }
    private static FileStream Open(string path, bool directory)
    {
        return OpenCore(path, directory, path);
    }
    private static string PublicPathSpelling(string path)
    {
        if (path != null && path.StartsWith("\\\\?\\UNC\\", StringComparison.OrdinalIgnoreCase))
        {
            string tail = path.Substring(8);
            int separator = tail.IndexOf('\\');
            if (separator > 0 && separator < tail.Length - 1 && tail[separator + 1] != '\\') return "\\\\" + tail;
        }
        else if (path != null && path.StartsWith("\\\\?\\", StringComparison.Ordinal) && path.Length > 7
            && ((path[4] >= 'A' && path[4] <= 'Z') || (path[4] >= 'a' && path[4] <= 'z'))
            && path[5] == ':' && path[6] == '\\') return path.Substring(4);
        Fail(); return null;
    }
    private static string PublicProcessPath(string canonical, bool directory, List<FileStream> held)
    {
        // Electron requires ordinary Win32 startup spelling. Reopen that exact
        // spelling against the admitted namespace identity before handing off;
        // do not let trimming or an alias redirect it to another object.
        string path = PublicPathSpelling(canonical);
        held.Add(OpenCore(path, directory, canonical));
        return path;
    }
    private static FileStream OpenCore(string path, bool directory, string expectedFinalPath)
    {
        SafeFileHandle handle = CreateFileW(path, 0x80000000, 1, IntPtr.Zero, 3, 0x00200000 | (directory ? 0x02000000u : 0), IntPtr.Zero);
        try
        {
            if (handle.IsInvalid) Fail();
            NativeFileInfo info;
            if (!GetFileInformationByHandle(handle, out info) || (info.attributes & Reparse) != 0
                || ((info.attributes & DirectoryAttribute) != 0) != directory
                || !String.Equals(FinalPath(handle).TrimEnd('\\'), expectedFinalPath.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase)) Fail();
            var stream = new FileStream(handle, FileAccess.Read);
            handle = null;
            return stream;
        }
        finally { if (handle != null) handle.Dispose(); }
    }
    private static string FinalPath(SafeFileHandle handle)
    {
        var buffer = new StringBuilder(32768);
        uint length = GetFinalPathNameByHandleW(handle, buffer, buffer.Capacity, 0);
        if (length == 0 || length >= buffer.Capacity) Fail();
        return buffer.ToString();
    }
    private static byte[] ReadBytes(string path, int maximum, List<FileStream> held)
    {
        FileStream stream = Open(path, false);
        held.Add(stream);
        {
            if (stream.Length < 1 || stream.Length > maximum) Fail();
            var bytes = new byte[(int)stream.Length];
            int offset = 0, count;
            while (offset < bytes.Length && (count = stream.Read(bytes, offset, bytes.Length - offset)) != 0) offset += count;
            if (offset != bytes.Length || stream.ReadByte() != -1) Fail();
            return bytes;
        }
    }
    private static void ExactTree(string root, HashSet<string> expected, List<FileStream> held)
    {
        var pending = new Stack<string>(); pending.Push("");
        int visited = 0;
        while (pending.Count != 0)
        {
            string relative = pending.Pop(), path = relative == "" ? root : Child(root, relative);
            if (held != null && relative != "") held.Add(Open(path, true));
            FindData data;
            IntPtr find = FindFirstFileW(path + "\\*", out data);
            if (find == new IntPtr(-1)) { if (Marshal.GetLastWin32Error() == 2) continue; Fail(); }
            try
            {
                do
                {
                    if (data.name == "." || data.name == "..") continue;
                    if (++visited > 200000 || (data.attributes & Reparse) != 0) Fail();
                    string child = relative == "" ? data.name : relative + "/" + data.name;
                    if (!Portable(child)) Fail();
                    if ((data.attributes & DirectoryAttribute) != 0) {
                        if (child.Split('/').Length > 128) Fail();
                        pending.Push(child);
                    }
                    else if (!expected.Remove(child)) Fail();
                } while (FindNextFileW(find, out data));
                if (Marshal.GetLastWin32Error() != 18) Fail();
            }
            finally { FindClose(find); }
        }
        if (expected.Count != 0) Fail();
    }

    [StructLayout(LayoutKind.Sequential)] private struct NativeFileInfo {
        public uint attributes, creationLow, creationHigh, accessLow, accessHigh, writeLow, writeHigh;
        public uint volume, sizeHigh, sizeLow, links, indexHigh, indexLow;
    }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] private struct FindData {
        public uint attributes, creationLow, creationHigh, accessLow, accessHigh, writeLow, writeHigh;
        public uint sizeHigh, sizeLow, reserved0, reserved1;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string name;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 14)] public string alternate;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern SafeFileHandle CreateFileW(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetFileInformationByHandle(SafeFileHandle handle, out NativeFileInfo info);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern uint GetFinalPathNameByHandleW(SafeFileHandle handle, StringBuilder path, int size, uint flags);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern uint GetFileAttributesW(string path);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr FindFirstFileW(string path, out FindData data);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool FindNextFileW(IntPtr find, out FindData data);
    [DllImport("kernel32.dll")] private static extern bool FindClose(IntPtr find);
}
