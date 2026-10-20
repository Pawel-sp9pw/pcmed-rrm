using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Win32.SafeHandles;
using PcMed.Common;

ApplicationConfiguration.Initialize();
using var mutex = new Mutex(true, "Local\\PcMedNotifier", out var acquired);
if (!acquired) return;
using var application = new NoticeContext();
Application.Run(application);

sealed class NoticeContext : ApplicationContext
{
    private readonly CancellationTokenSource shutdown = new();
    private readonly Control dispatcher = new();
    private readonly HashSet<string> seen = [];
    private int openNotices;

    public NoticeContext()
    {
        dispatcher.CreateControl();
        _ = Listen(shutdown.Token);
    }

    private async Task Listen(CancellationToken cancellation)
    {
        while (!cancellation.IsCancellationRequested)
        {
            try
            {
                using var pipe = new NamedPipeClientStream(".", "PcMed.Notices.v1", PipeDirection.InOut, PipeOptions.Asynchronous);
                await pipe.ConnectAsync(5000, cancellation);
                if (!GetNamedPipeServerProcessId(pipe.SafePipeHandle, out var serverId) ||
                    System.Diagnostics.Process.GetProcessById((int)serverId).SessionId != 0)
                    throw new InvalidOperationException("Notice server must run as a service in session zero.");
                using var reader = new StreamReader(pipe);
                var buffer = new char[32768];
                var length = 0;
                while (length < buffer.Length)
                {
                    var count = await reader.ReadAsync(buffer.AsMemory(length, 1), cancellation);
                    if (count == 0 || buffer[length] == '\n') break;
                    length += count;
                }
                if (length == buffer.Length) throw new InvalidOperationException("Notice too large.");
                var notice = JsonSerializer.Deserialize<Notice>(buffer.AsSpan(0, length), Wire.Json);
                if (notice is not null && Guid.TryParse(notice.Id, out _) && notice.Title.Length <= 120 && notice.Body.Length <= 4000)
                {
                    var shown = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                    dispatcher.BeginInvoke(() => shown.TrySetResult(ShowNotice(notice)));
                    if (await shown.Task.WaitAsync(cancellation))
                    {
                        using var writer = new StreamWriter(pipe, leaveOpen: true);
                        await writer.WriteAsync(notice.Id.AsMemory(), cancellation);
                        await writer.FlushAsync(cancellation);
                    }
                }
            }
            catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { return; }
            catch (Exception exception) when (exception is IOException or TimeoutException or InvalidOperationException or JsonException or ArgumentException) { }
            try { await Task.Delay(2000, cancellation); }
            catch (OperationCanceledException) { return; }
        }
    }

    private bool ShowNotice(Notice notice)
    {
        if (seen.Contains(notice.Id)) return true;
        if (openNotices >= 10) return false;
        seen.Add(notice.Id);
        if (seen.Count > 1000) seen.Clear();
        openNotices++;
        var form = new Form { Text = "PC MED — komunikat", Width = 540, Height = 340, StartPosition = FormStartPosition.CenterScreen };
        var text = new TextBox { Multiline = true, ReadOnly = true, Dock = DockStyle.Fill, ScrollBars = ScrollBars.Vertical,
            Text = notice.Title + Environment.NewLine + Environment.NewLine + notice.Body, Font = new Font("Segoe UI", 12) };
        var close = new Button { Text = "Zamknij", Dock = DockStyle.Bottom, Height = 44 };
        close.Click += (_, _) => form.Close();
        form.Controls.Add(text);
        form.Controls.Add(close);
        form.FormClosed += (_, _) => { openNotices--; form.Dispose(); };
        form.Show();
        return true;
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) { shutdown.Cancel(); shutdown.Dispose(); dispatcher.Dispose(); }
        base.Dispose(disposing);
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetNamedPipeServerProcessId(SafePipeHandle pipe, out uint serverProcessId);
}
