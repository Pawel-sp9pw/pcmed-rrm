using System.Security.Cryptography;
using PcMed.Common;

namespace PcMed.Gateway;

public sealed class ArtifactCache(GatewayOptions options, SecretFile secrets) : IDisposable
{
    private readonly SemaphoreSlim gate = new(1, 1);
    private readonly HttpClient downloads = new(new HttpClientHandler { AllowAutoRedirect = false }) { Timeout = TimeSpan.FromMinutes(15) };

    public async Task<string> Resolve(ArtifactTicket ticket, CancellationToken cancellation)
    {
        var uri = Policy.ArtifactUrl(ticket.Url, options.ArtifactHosts);
        if (ticket.Sha256.Length != 64 || !ticket.Sha256.All(Uri.IsHexDigit)) throw new InvalidOperationException("Invalid hash.");
        await gate.WaitAsync(cancellation);
        try
        {
            var directory = Directory.CreateDirectory(Path.Combine(secrets.Root, "cache"));
            var path = Path.Combine(directory.FullName, ticket.Sha256.ToLowerInvariant() + ".bin");
            if (File.Exists(path))
            {
                await using var existing = File.OpenRead(path);
                var hash = Convert.ToHexString(await SHA256.HashDataAsync(existing, cancellation));
                if (hash.Equals(ticket.Sha256, StringComparison.OrdinalIgnoreCase)) return path;
                existing.Close();
                File.Delete(path);
            }
            var temporary = path + ".part";
            try
            {
                foreach (var oldPartial in directory.GetFiles("*.part")) oldPartial.Delete();
                using var response = await downloads.GetAsync(uri, HttpCompletionOption.ResponseHeadersRead, cancellation);
                if (!response.IsSuccessStatusCode || response.Content.Headers.ContentLength > options.MaxArtifactBytes)
                    throw new InvalidOperationException("Installer unavailable, redirected or oversized.");
                await using (var source = await response.Content.ReadAsStreamAsync(cancellation))
                await using (var target = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    var buffer = new byte[65536];
                    long total = 0;
                    int count;
                    while ((count = await source.ReadAsync(buffer, cancellation)) > 0)
                    {
                        total += count;
                        if (total > options.MaxArtifactBytes) throw new InvalidOperationException("Installer too large.");
                        await target.WriteAsync(buffer.AsMemory(0, count), cancellation);
                    }
                }
                await using (var downloaded = File.OpenRead(temporary))
                {
                    var hash = Convert.ToHexString(await SHA256.HashDataAsync(downloaded, cancellation));
                    if (!hash.Equals(ticket.Sha256, StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("SHA-256 mismatch.");
                }
                var files = directory.GetFiles("*.bin").OrderBy(file => file.LastWriteTimeUtc).ToList();
                var size = files.Sum(file => file.Length) + new FileInfo(temporary).Length;
                foreach (var old in files)
                {
                    if (size <= options.MaxCacheBytes) break;
                    size -= old.Length;
                    old.Delete();
                }
                if (size > options.MaxCacheBytes) throw new InvalidOperationException("Cache quota exceeded.");
                File.Move(temporary, path);
                return path;
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        finally { gate.Release(); }
    }

    public void Dispose() { downloads.Dispose(); gate.Dispose(); }
}
