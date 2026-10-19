using System.Text.Json;

namespace PcMed.Common;

public static class Wire
{
    public static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
    };
}

public sealed record WorkSpec(string? Url, string? Sha256, string? Script, string[]? Arguments, string? Title, string? Body);
public sealed record WorkItem(string Id, string Claim, string Kind, WorkSpec Spec, int TimeoutSeconds);
public sealed record WorkResult(string Claim, string State, int? ExitCode, string Output);
public sealed record Journal(WorkItem Job, WorkResult? Result);
public sealed record Credential(string Token, string? DeviceId = null);
public sealed record Notice(string Id, string Title, string Body);

public static class Policy
{
    public static Uri HttpsEndpoint(string value)
    {
        var uri = new Uri(value, UriKind.Absolute);
        if (uri.Scheme != Uri.UriSchemeHttps || !string.IsNullOrEmpty(uri.UserInfo) ||
            uri.AbsolutePath != "/" || !string.IsNullOrEmpty(uri.Query) || !string.IsNullOrEmpty(uri.Fragment))
            throw new InvalidOperationException("Endpoint must be an HTTPS origin without a path or credentials.");
        return uri;
    }

    public static Uri ArtifactUrl(string value, IEnumerable<string> allowedHosts)
    {
        var uri = new Uri(value, UriKind.Absolute);
        if (uri.Scheme != Uri.UriSchemeHttps || !string.IsNullOrEmpty(uri.UserInfo) ||
            !string.IsNullOrEmpty(uri.Fragment) || !allowedHosts.Contains(uri.IdnHost, StringComparer.OrdinalIgnoreCase))
            throw new InvalidOperationException("Installer URL is not allowlisted HTTPS.");
        return uri;
    }

    public static void Validate(WorkItem job)
    {
        if (!Guid.TryParse(job.Id, out _) || !Guid.TryParse(job.Claim, out _) || job.TimeoutSeconds is < 10 or > 3600)
            throw new InvalidOperationException("Invalid job envelope.");
        if (job.Kind == "message")
        {
            if (string.IsNullOrWhiteSpace(job.Spec.Title) || job.Spec.Title.Length > 120 ||
                string.IsNullOrWhiteSpace(job.Spec.Body) || job.Spec.Body.Length > 4000)
                throw new InvalidOperationException("Invalid notice.");
            return;
        }
        if (job.Kind is not ("msi" or "exe" or "bat" or "powershell"))
            throw new InvalidOperationException("Unsupported job kind.");
        if (job.Spec.Sha256 is not { Length: 64 } || !job.Spec.Sha256.All(Uri.IsHexDigit))
            throw new InvalidOperationException("SHA-256 is required.");
        if (job.Kind is "bat" or "powershell")
        {
            if (string.IsNullOrEmpty(job.Spec.Script) || job.Spec.Script.Length > 65536 ||
                job.Spec.Url is not null || job.Spec.Arguments is { Length: > 0 })
                throw new InvalidOperationException("Invalid script specification.");
        }
        else if (job.Spec.Url is null || job.Spec.Script is not null || job.Spec.Arguments is { Length: > 64 } ||
                 (job.Spec.Arguments ?? []).Any(argument => argument.Length > 2048 || argument.IndexOfAny(['\0', '\r', '\n']) >= 0))
            throw new InvalidOperationException("Invalid installer specification.");
    }

    public static bool RelayRoute(string method, string path) => method == "POST" &&
        (path is "/api/agent/enroll" or "/api/agent/heartbeat" or "/api/agent/next" ||
         path.StartsWith("/api/agent/results/", StringComparison.Ordinal) &&
         Guid.TryParseExact(path["/api/agent/results/".Length..], "D", out _));
}
