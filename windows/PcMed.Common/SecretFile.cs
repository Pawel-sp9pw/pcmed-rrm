using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.Json;

namespace PcMed.Common;

public sealed class SecretFile
{
    public string Root { get; }

    public SecretFile(string root)
    {
        Root = Path.GetFullPath(root);
        var directory = Directory.CreateDirectory(Root);
        if ((directory.Attributes & FileAttributes.ReparsePoint) != 0)
            throw new InvalidOperationException("State directory must not be a reparse point.");
        var security = new DirectorySecurity();
        security.SetAccessRuleProtection(true, false);
        foreach (var identity in new[] { WellKnownSidType.LocalSystemSid, WellKnownSidType.BuiltinAdministratorsSid })
            security.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(identity, null), FileSystemRights.FullControl,
                InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
        directory.SetAccessControl(security);
    }

    private string PathFor(string name)
    {
        if (Path.GetFileName(name) != name || name is "." or "..")
            throw new ArgumentException("File name required.");
        return Path.Combine(Root, name);
    }

    public void Save<T>(string name, T value)
    {
        var protectedBytes = ProtectedData.Protect(JsonSerializer.SerializeToUtf8Bytes(value, Wire.Json), null, DataProtectionScope.LocalMachine);
        var path = PathFor(name);
        var temporary = path + ".tmp";
        using (var stream = new FileStream(temporary, FileMode.Create, FileAccess.Write, FileShare.None))
        {
            stream.Write(protectedBytes);
            stream.Flush(true);
        }
        File.Move(temporary, path, true);
    }

    public T? Load<T>(string name)
    {
        var path = PathFor(name);
        if (!File.Exists(path)) return default;
        return JsonSerializer.Deserialize<T>(ProtectedData.Unprotect(File.ReadAllBytes(path), null, DataProtectionScope.LocalMachine), Wire.Json);
    }

    public void Remove(string name) => File.Delete(PathFor(name));

    public static string ReadToken()
    {
        Console.Write("One-time / gateway token: ");
        var token = new StringBuilder();
        while (true)
        {
            var key = Console.ReadKey(true);
            if (key.Key == ConsoleKey.Enter) break;
            if (key.Key == ConsoleKey.Backspace && token.Length > 0) token.Length--;
            else if (!char.IsControl(key.KeyChar)) token.Append(key.KeyChar);
        }
        Console.WriteLine();
        if (token.Length is < 32 or > 200) throw new InvalidOperationException("Invalid token length.");
        return token.ToString();
    }
}
