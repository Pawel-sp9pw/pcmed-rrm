using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Extensions.Options;
using PcMed.Common;

namespace PcMed.Agent;

public sealed class Executor(SecretFile secrets, NoticePipe notices, IOptions<AgentOptions> options, HttpClient agentClient)
{
    public async Task<WorkResult> Execute(WorkItem job, CancellationToken cancellation)
    {
        Policy.Validate(job);
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(TimeSpan.FromSeconds(job.TimeoutSeconds));
        var directory = Path.Combine(secrets.Root, job.Id);
        var executionStarted = false;
        try
        {
            if (job.Kind == "message")
            {
                await notices.Deliver(new Notice(job.Id, job.Spec.Title!, job.Spec.Body!), deadline.Token);
                return new WorkResult(job.Claim, "succeeded", 0, "Delivered to a logged-on user session; reading is not confirmed.");
            }
            Directory.CreateDirectory(directory);
            var path = Path.Combine(directory, "payload." + (job.Kind == "powershell" ? "ps1" : job.Kind));
            if (job.Spec.Script is not null)
                await File.WriteAllTextAsync(path, job.Spec.Script, new UTF8Encoding(job.Kind == "powershell"), deadline.Token);
            else
                await Download(job, path, deadline.Token);
            await using (var stream = File.OpenRead(path))
            {
                var hash = Convert.ToHexString(await SHA256.HashDataAsync(stream, deadline.Token));
                if (!hash.Equals(job.Spec.Sha256, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidOperationException("SHA-256 mismatch.");
            }
            var start = StartInfo(job, path);
            start.WorkingDirectory = directory;
            using var process = Process.Start(start) ?? throw new InvalidOperationException("Process did not start.");
            executionStarted = true;
            using var processScope = new ProcessScope(process);
            var output = new StringBuilder();
            var outputLock = new object();
            var stdout = Capture(process.StandardOutput, output, outputLock);
            var stderr = Capture(process.StandardError, output, outputLock);
            try { await process.WaitForExitAsync(deadline.Token); }
            catch
            {
                if (!process.HasExited) process.Kill(entireProcessTree: true);
                await process.WaitForExitAsync(CancellationToken.None);
                throw;
            }
            await Task.WhenAll(stdout, stderr).WaitAsync(TimeSpan.FromSeconds(5), CancellationToken.None);
            var success = process.ExitCode == 0 || job.Kind == "msi" && process.ExitCode == 3010;
            return new WorkResult(job.Claim, success ? "succeeded" : "failed", process.ExitCode, output.ToString());
        }
        catch (OperationCanceledException)
        {
            return new WorkResult(job.Claim, "unknown", null, "Execution interrupted or deadline reached; process tree stopped, effects may be partial.");
        }
        catch (Exception exception)
        {
            return new WorkResult(job.Claim, executionStarted ? "unknown" : "failed", null, $"Execution failed: {exception.GetType().Name}.");
        }
        finally
        {
            if (Directory.Exists(directory))
            {
                try { Directory.Delete(directory, true); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }
    }

    public static ProcessStartInfo StartInfo(WorkItem job, string path)
    {
        var system = Environment.GetFolderPath(Environment.SpecialFolder.System);
        var start = new ProcessStartInfo { UseShellExecute = false, CreateNoWindow = true, RedirectStandardError = true, RedirectStandardOutput = true };
        switch (job.Kind)
        {
            case "powershell":
                start.FileName = Path.Combine(system, "WindowsPowerShell", "v1.0", "powershell.exe");
                foreach (var argument in new[] { "-NoLogo", "-NoProfile", "-NonInteractive", "-File", path }) start.ArgumentList.Add(argument);
                break;
            case "bat":
                start.FileName = Path.Combine(system, "cmd.exe");
                start.Arguments = $"/d /s /c \"\"{path}\"\"";
                break;
            case "msi":
                start.FileName = Path.Combine(system, "msiexec.exe");
                foreach (var argument in new[] { "/i", path, "/qn", "/norestart" }) start.ArgumentList.Add(argument);
                foreach (var argument in job.Spec.Arguments ?? []) start.ArgumentList.Add(argument);
                break;
            case "exe":
                start.FileName = path;
                foreach (var argument in job.Spec.Arguments ?? []) start.ArgumentList.Add(argument);
                break;
            default: throw new InvalidOperationException("Unsupported process kind.");
        }
        return start;
    }

    private async Task Download(WorkItem job, string path, CancellationToken cancellation)
    {
        using var directClient = new HttpClient(new HttpClientHandler { AllowAutoRedirect = false }) { Timeout = Timeout.InfiniteTimeSpan };
        var client = options.Value.UseGateway ? agentClient : directClient;
        var uri = options.Value.UseGateway
            ? new Uri(client.BaseAddress!, $"api/agent/artifact/{job.Id}/{job.Claim}")
            : Policy.ArtifactUrl(job.Spec.Url!, options.Value.ArtifactHosts);
        using var response = await client.GetAsync(uri, HttpCompletionOption.ResponseHeadersRead, cancellation);
        response.EnsureSuccessStatusCode();
        if ((int)response.StatusCode is >= 300 and < 400 || response.Content.Headers.ContentLength > options.Value.MaxArtifactBytes)
            throw new InvalidOperationException("Redirect or oversized installer rejected.");
        await using var source = await response.Content.ReadAsStreamAsync(cancellation);
        await using var target = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None);
        var buffer = new byte[65536];
        long total = 0;
        int count;
        while ((count = await source.ReadAsync(buffer, cancellation)) > 0)
        {
            total += count;
            if (total > options.Value.MaxArtifactBytes) throw new InvalidOperationException("Installer too large.");
            await target.WriteAsync(buffer.AsMemory(0, count), cancellation);
        }
    }

    private static async Task Capture(StreamReader reader, StringBuilder output, object outputLock)
    {
        var buffer = new char[2048];
        int count;
        while ((count = await reader.ReadAsync(buffer)) > 0)
            lock (outputLock)
                output.Append(buffer, 0, Math.Min(count, 32768 - output.Length));
    }
}
