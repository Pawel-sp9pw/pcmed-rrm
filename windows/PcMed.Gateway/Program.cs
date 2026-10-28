using System.Net.Http.Headers;
using System.Net.Http.Json;
using Microsoft.AspNetCore.RateLimiting;
using PcMed.Common;
using PcMed.Gateway;
using System.Security.Cryptography.X509Certificates;

if (args.Contains("--check-certificate"))
{
    var certificateIndex = Array.IndexOf(args, "--thumbprint");
    var addressIndex = Array.IndexOf(args, "--lan-address");
    if (certificateIndex < 0 || addressIndex < 0) throw new InvalidOperationException("Certificate thumbprint and LAN address required.");
    using var store = new X509Store(StoreName.My, StoreLocation.LocalMachine);
    store.Open(OpenFlags.ReadOnly);
    var matches = store.Certificates.Find(X509FindType.FindByThumbprint, args[certificateIndex + 1], true);
    if (matches.Count != 1 || !matches[0].HasPrivateKey || !matches[0].MatchesHostname(args[addressIndex + 1], false, false) ||
        !matches[0].Extensions.OfType<X509EnhancedKeyUsageExtension>().Any(extension => extension.EnhancedKeyUsages.Cast<System.Security.Cryptography.Oid>().Any(oid => oid.Value == "1.3.6.1.5.5.7.3.1")))
        throw new InvalidOperationException("Use a trusted, valid serverAuth certificate with private key and the gateway LAN IPv4 in its SAN.");
    Console.WriteLine(matches[0].GetCertHashString(System.Security.Cryptography.HashAlgorithmName.SHA256));
    return;
}

var builder = WebApplication.CreateBuilder(new WebApplicationOptions { Args = args, ContentRootPath = AppContext.BaseDirectory });
builder.Host.UseWindowsService(options => options.ServiceName = "PcMedGateway");
var options = builder.Configuration.GetSection("Gateway").Get<GatewayOptions>() ?? throw new InvalidOperationException("Gateway configuration missing.");
var upstream = Policy.HttpsEndpoint(options.Upstream);
var secrets = new SecretFile(options.StateDirectory);
if (args.Contains("--provision"))
{
    if (secrets.Load<Credential>("credential.bin") is not null) throw new InvalidOperationException("Already provisioned. Revoke the old gateway credential deliberately before changing it.");
    using var client = new HttpClient(SecureTransport.Handler(options.UpstreamCertificateSha256)) { BaseAddress = upstream, Timeout = TimeSpan.FromSeconds(30) };
    using var preflight = await client.GetAsync("realms/pcmed/.well-known/openid-configuration");
    preflight.EnsureSuccessStatusCode();
    secrets.Save("credential.bin", new Credential(SecretFile.ReadToken()));
    Console.WriteLine("Gateway credential saved with machine protection.");
    return;
}
var credential = secrets.Load<Credential>("credential.bin") ?? throw new InvalidOperationException("Run --provision as administrator first.");
builder.WebHost.ConfigureKestrel(server =>
{
    if (!string.IsNullOrWhiteSpace(options.ServerCertificateThumbprint))
    {
        using var store = new X509Store(StoreName.My, StoreLocation.LocalMachine);
        store.Open(OpenFlags.ReadOnly);
        var certificates = store.Certificates.Find(X509FindType.FindByThumbprint, options.ServerCertificateThumbprint, true);
        if (certificates.Count != 1 || !certificates[0].HasPrivateKey) throw new InvalidOperationException("Configured TLS certificate is unavailable or invalid.");
        server.ConfigureHttpsDefaults(https => https.ServerCertificate = certificates[0]);
    }
    server.Limits.MaxRequestBodySize = 262144;
    server.Limits.MaxConcurrentConnections = 200;
    server.Limits.RequestHeadersTimeout = TimeSpan.FromSeconds(15);
});
builder.Services.AddRateLimiter(configuration => configuration.AddConcurrencyLimiter("relay", limit =>
{
    limit.PermitLimit = 64;
    limit.QueueLimit = 0;
}));
builder.Services.AddSingleton(new HttpClient(SecureTransport.Handler(options.UpstreamCertificateSha256)) { BaseAddress = upstream, Timeout = TimeSpan.FromSeconds(30) });
builder.Services.AddSingleton(new ArtifactCache(options, secrets));
var app = builder.Build();
app.Use(async (context, next) =>
{
    context.Response.Headers.CacheControl = "no-store";
    if (!context.Request.IsHttps) { context.Response.StatusCode = 400; return; }
    if (!LanPolicy.Contains(options.AllowedSubnet, context.Connection.RemoteIpAddress)) { context.Response.StatusCode = 403; return; }
    await next(context);
});
app.UseRateLimiter();
app.MapGet("/.well-known/pcmed-gateway", () => Results.Json(new { service = "pcmed-gateway", protocol = 1 })).RequireRateLimiting("relay");

HttpRequestMessage UpstreamRequest(HttpContext context, string path, HttpMethod method)
{
    var request = new HttpRequestMessage(method, path);
    if (AuthenticationHeaderValue.TryParse(context.Request.Headers.Authorization, out var auth) && auth.Scheme == "Bearer")
        request.Headers.Authorization = auth;
    request.Headers.Add("X-PCMED-Gateway", credential.Token);
    return request;
}

app.MapGet("/api/agent/artifact/{jobId:guid}/{claim:guid}", async (Guid jobId, Guid claim, HttpContext context, HttpClient client, ArtifactCache cache) =>
{
    using var ticketRequest = UpstreamRequest(context, $"api/agent/artifact-ticket/{jobId:D}/{claim:D}", HttpMethod.Get);
    using var ticketResponse = await client.SendAsync(ticketRequest, context.RequestAborted);
    if (!ticketResponse.IsSuccessStatusCode) { context.Response.StatusCode = (int)ticketResponse.StatusCode; return; }
    var ticket = await ticketResponse.Content.ReadFromJsonAsync<ArtifactTicket>(Wire.Json, context.RequestAborted)
        ?? throw new InvalidOperationException("Empty artifact ticket.");
    try
    {
        var path = await cache.Resolve(ticket, context.RequestAborted);
        context.Response.ContentType = "application/octet-stream";
        await using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read | FileShare.Delete);
        context.Response.ContentLength = stream.Length;
        await stream.CopyToAsync(context.Response.Body, context.RequestAborted);
    }
    catch (Exception exception) when (exception is HttpRequestException or IOException or InvalidOperationException)
    {
        if (!context.Response.HasStarted) context.Response.StatusCode = 502;
        else context.Abort();
    }
}).RequireRateLimiting("relay");

app.MapPost("/api/agent/{**route}", async (HttpContext context, HttpClient client) =>
{
    if (!Policy.RelayRoute(context.Request.Method, context.Request.Path.Value ?? "") || context.Request.QueryString.HasValue)
    { context.Response.StatusCode = 404; return; }
    using var request = UpstreamRequest(context, context.Request.Path.Value!.TrimStart('/'), HttpMethod.Post);
    request.Content = new StreamContent(context.Request.Body);
    request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
    try
    {
        using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, context.RequestAborted);
        context.Response.StatusCode = (int)response.StatusCode;
        context.Response.ContentType = "application/json";
        await response.Content.CopyToAsync(context.Response.Body, context.RequestAborted);
    }
    catch (HttpRequestException) { context.Response.StatusCode = 502; }
    catch (OperationCanceledException) when (!context.RequestAborted.IsCancellationRequested) { context.Response.StatusCode = 504; }
}).RequireRateLimiting("relay");
await app.RunAsync();

namespace PcMed.Gateway
{
    public sealed class GatewayOptions
    {
        public string Upstream { get; set; } = "https://172.20.0.8:38443";
        public string? ServerCertificateThumbprint { get; set; }
        public string? UpstreamCertificateSha256 { get; set; }
        public string AllowedSubnet { get; set; } = "";
        public string StateDirectory { get; set; } = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "PcMed", "Gateway");
        public string[] ArtifactHosts { get; set; } = [];
        public long MaxArtifactBytes { get; set; } = 536870912;
        public long MaxCacheBytes { get; set; } = 10737418240;
    }
    public sealed record ArtifactTicket(string Url, string Sha256);
}
