using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

namespace PcMed.Common;

public static class SecureTransport
{
    public static string Fingerprint(string value)
    {
        var normalized = value.Replace(":", "").Replace(" ", "").ToUpperInvariant();
        if (normalized.Length != 64 || !normalized.All(Uri.IsHexDigit))
            throw new InvalidOperationException("Expected SHA-256 of the server certificate (64 hexadecimal digits).");
        return normalized;
    }

    public static bool AcceptCertificate(X509Certificate2? certificate, SslPolicyErrors errors, string expected)
    {
        return certificate is not null && errors == SslPolicyErrors.None &&
            certificate.NotBefore.ToUniversalTime() <= DateTime.UtcNow && certificate.NotAfter.ToUniversalTime() > DateTime.UtcNow &&
            CryptographicOperations.FixedTimeEquals(certificate.GetCertHash(HashAlgorithmName.SHA256), Convert.FromHexString(Fingerprint(expected)));
    }

    public static HttpClientHandler Handler(string? fingerprint = null)
    {
        var handler = new HttpClientHandler { AllowAutoRedirect = false, UseProxy = false, CheckCertificateRevocationList = true };
        if (!string.IsNullOrWhiteSpace(fingerprint))
        {
            var expected = Fingerprint(fingerprint);
            handler.ServerCertificateCustomValidationCallback = (_, certificate, _, errors) => AcceptCertificate(certificate, errors, expected);
        }
        return handler;
    }
}
