using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using Microsoft.Win32.SafeHandles;
using PcMed.Common;

namespace PcMed.Agent;

public sealed class NoticePipe
{
    public async Task Deliver(Notice notice, CancellationToken cancellation)
    {
        var security = new PipeSecurity();
        security.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null), PipeAccessRights.FullControl, AccessControlType.Allow));
        security.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null), PipeAccessRights.FullControl, AccessControlType.Allow));
        security.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(WellKnownSidType.InteractiveSid, null), PipeAccessRights.ReadWrite, AccessControlType.Allow));
        security.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(WellKnownSidType.NetworkSid, null), PipeAccessRights.FullControl, AccessControlType.Deny));
        while (true)
        {
            await using var pipe = NamedPipeServerStreamAcl.Create("PcMed.Notices.v1", PipeDirection.InOut, 1,
                PipeTransmissionMode.Byte, PipeOptions.Asynchronous | PipeOptions.FirstPipeInstance, 0, 16384, security);
            await pipe.WaitForConnectionAsync(cancellation);
            if (!GetNamedPipeClientProcessId(pipe.SafePipeHandle, out var processId) ||
                Process.GetProcessById((int)processId).SessionId == 0)
                continue;
            await using var writer = new StreamWriter(pipe, new UTF8Encoding(false), leaveOpen: true);
            await writer.WriteLineAsync(JsonSerializer.Serialize(notice, Wire.Json).AsMemory(), cancellation);
            await writer.FlushAsync(cancellation);
            using var reader = new StreamReader(pipe, leaveOpen: true);
            var acknowledgment = new char[36];
            var received = 0;
            while (received < acknowledgment.Length)
            {
                var count = await reader.ReadAsync(acknowledgment.AsMemory(received), cancellation);
                if (count == 0) break;
                received += count;
            }
            if (received == acknowledgment.Length && new string(acknowledgment) == notice.Id) return;
        }
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetNamedPipeClientProcessId(SafePipeHandle pipe, out uint clientProcessId);
}
