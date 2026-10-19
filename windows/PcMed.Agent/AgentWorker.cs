using System.Net;
using System.Net.Http.Json;
using PcMed.Common;

namespace PcMed.Agent;

public sealed class AgentWorker(HttpClient client, SecretFile secrets, Executor executor, ILogger<AgentWorker> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var heartbeat = Heartbeats(stoppingToken);
        try
        {
            while (!stoppingToken.IsCancellationRequested)
            {
                try
                {
                    var pending = secrets.Load<Journal>("journal.bin");
                    if (pending is not null)
                    {
                        var result = pending.Result ?? new WorkResult(pending.Job.Claim, "unknown", null, "Agent restarted during execution; automatic replay disabled.");
                        secrets.Save("journal.bin", pending with { Result = result });
                        using var reportTimeout = CancellationTokenSource.CreateLinkedTokenSource(stoppingToken);
                        reportTimeout.CancelAfter(TimeSpan.FromSeconds(30));
                        using var report = await client.PostAsJsonAsync($"api/agent/results/{pending.Job.Id}", result, Wire.Json, reportTimeout.Token);
                        report.EnsureSuccessStatusCode();
                        secrets.Remove("journal.bin");
                    }
                    using var pollTimeout = CancellationTokenSource.CreateLinkedTokenSource(stoppingToken);
                    pollTimeout.CancelAfter(TimeSpan.FromSeconds(30));
                    using var response = await client.PostAsync("api/agent/next", null, pollTimeout.Token);
                    response.EnsureSuccessStatusCode();
                    if (response.StatusCode != HttpStatusCode.NoContent)
                    {
                        var job = await response.Content.ReadFromJsonAsync<WorkItem>(Wire.Json, stoppingToken) ?? throw new InvalidOperationException("Empty job.");
                        Policy.Validate(job);
                        secrets.Save("journal.bin", new Journal(job, null));
                        var result = await executor.Execute(job, stoppingToken);
                        secrets.Save("journal.bin", new Journal(job, result));
                        continue;
                    }
                }
                catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { break; }
                catch (Exception exception)
                {
                    logger.LogWarning("Agent cycle failed ({Type}); retrying after backoff.", exception.GetType().Name);
                }
                await Task.Delay(TimeSpan.FromSeconds(10 + Random.Shared.Next(5)), stoppingToken);
            }
        }
        finally
        {
            await heartbeat;
        }
    }

    private async Task Heartbeats(CancellationToken cancellation)
    {
        while (!cancellation.IsCancellationRequested)
        {
            try
            {
                using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
                timeout.CancelAfter(TimeSpan.FromSeconds(30));
                using var response = await client.PostAsJsonAsync("api/agent/heartbeat", new { agent_version = "0.1.0" }, Wire.Json, timeout.Token);
                response.EnsureSuccessStatusCode();
            }
            catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { return; }
            catch (Exception exception) { logger.LogWarning("Heartbeat failed ({Type}).", exception.GetType().Name); }
            try { await Task.Delay(TimeSpan.FromSeconds(30), cancellation); }
            catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { return; }
        }
    }
}
