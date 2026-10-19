using System.Net.Http.Headers;
using System.Net.Http.Json;
using PcMed.Common;
using PcMed.Agent;

var builder = Host.CreateApplicationBuilder(new HostApplicationBuilderSettings { Args = args, ContentRootPath = AppContext.BaseDirectory });
builder.Services.AddWindowsService(options => options.ServiceName = "PcMedAgent");
builder.Services.Configure<AgentOptions>(builder.Configuration.GetSection("Agent"));
var options = builder.Configuration.GetSection("Agent").Get<AgentOptions>() ?? throw new InvalidOperationException("Agent configuration missing.");
var endpoint = Policy.HttpsEndpoint(options.Endpoint);
var secrets = new SecretFile(options.StateDirectory);
builder.Services.AddSingleton(secrets);
builder.Services.AddSingleton(provider =>
{
    var credential = secrets.Load<Credential>("credential.bin") ?? throw new InvalidOperationException("Run --enroll as administrator first.");
    var client = new HttpClient(new HttpClientHandler { AllowAutoRedirect = false }) { BaseAddress = endpoint, Timeout = Timeout.InfiniteTimeSpan };
    client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", credential.Token);
    return client;
});
builder.Services.AddSingleton<NoticePipe>();
builder.Services.AddSingleton<Executor>();
builder.Services.AddHostedService<AgentWorker>();
if (args.Contains("--enroll"))
{
    if (secrets.Load<Credential>("credential.bin") is not null) throw new InvalidOperationException("Already enrolled. Revoke and remove the old credential deliberately before re-enrollment.");
    using var client = new HttpClient(new HttpClientHandler { AllowAutoRedirect = false }) { BaseAddress = endpoint };
    using var response = await client.PostAsJsonAsync("api/agent/enroll", new { token = SecretFile.ReadToken(), hostname = Environment.MachineName, os_version = Environment.OSVersion.VersionString }, Wire.Json);
    response.EnsureSuccessStatusCode();
    var credential = await response.Content.ReadFromJsonAsync<Credential>(Wire.Json) ?? throw new InvalidOperationException("Empty enrollment response.");
    secrets.Save("credential.bin", credential);
    Console.WriteLine("Agent enrolled. Credential saved with machine protection.");
    return;
}
using var mutex = new Mutex(true, "Global\\PcMedAgent", out var acquired);
if (!acquired) throw new InvalidOperationException("Another agent instance is running.");
await builder.Build().RunAsync();

namespace PcMed.Agent
{
    public sealed class AgentOptions
    {
        public string Endpoint { get; set; } = "https://gateway.example.test:7443";
        public string StateDirectory { get; set; } = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "PcMed", "Agent");
        public string[] ArtifactHosts { get; set; } = [];
        public long MaxArtifactBytes { get; set; } = 536870912;
        public bool UseGateway { get; set; } = true;
    }
}
