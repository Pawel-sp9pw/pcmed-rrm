using System.Net;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using PcMed.Agent;
using PcMed.Common;
using Xunit;

namespace PcMed.Tests;

public sealed class DiscoveryTests
{
    [Theory]
    [InlineData("192.168.20.15", 24, 254)]
    [InlineData("10.4.0.4", 22, 1022)]
    [InlineData("172.20.0.1", 30, 2)]
    public void ScanIsBoundedAndOmitsNetworkAndBroadcast(string address, int prefix, int count)
    {
        var targets = GatewayDiscovery.Targets(IPAddress.Parse(address), prefix);
        Assert.Equal(count, targets.Length);
        Assert.All(targets, target => Assert.True(GatewayDiscovery.PrivateAddress(target)));
        Assert.Equal(targets.Length, targets.Distinct().Count());
    }

    [Theory]
    [InlineData("8.8.8.8", 24)]
    [InlineData("127.0.0.1", 24)]
    [InlineData("169.254.0.1", 24)]
    [InlineData("10.0.0.1", 16)]
    [InlineData("10.0.0.1", 31)]
    [InlineData("::1", 24)]
    public void ScanRejectsPublicOrExcessiveTargets(string address, int prefix) =>
        Assert.Throws<InvalidOperationException>(() => GatewayDiscovery.Targets(IPAddress.Parse(address), prefix));

    [Theory]
    [InlineData("192.168.20.0/24", "192.168.20.5", true)]
    [InlineData("192.168.20.0/24", "::ffff:192.168.20.5", true)]
    [InlineData("192.168.20.0/24", "192.168.21.5", false)]
    [InlineData("192.168.20.5/24", "192.168.20.5", false)]
    [InlineData("0.0.0.0/0", "192.168.20.5", false)]
    [InlineData("8.8.8.0/24", "8.8.8.8", false)]
    [InlineData("10.0.0.0/7", "10.0.0.1", false)]
    [InlineData("invalid", "192.168.20.5", false)]
    public void GatewayEnforcesPrivateLanEvenWithoutFirewall(string subnet, string address, bool expected) =>
        Assert.Equal(expected, LanPolicy.Contains(subnet, IPAddress.Parse(address)));

    [Fact]
    public void CertificatePinDoesNotBypassChainOrHostnameValidation()
    {
        using var key = RSA.Create(2048);
        var request = new CertificateRequest("CN=gateway.test", key, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        using var certificate = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddMinutes(-1), DateTimeOffset.UtcNow.AddDays(1));
        var pin = certificate.GetCertHashString(HashAlgorithmName.SHA256);
        Assert.True(SecureTransport.AcceptCertificate(certificate, SslPolicyErrors.None, pin));
        Assert.False(SecureTransport.AcceptCertificate(certificate, SslPolicyErrors.RemoteCertificateChainErrors, pin));
        Assert.False(SecureTransport.AcceptCertificate(certificate, SslPolicyErrors.RemoteCertificateNameMismatch, pin));
        Assert.False(SecureTransport.AcceptCertificate(certificate, SslPolicyErrors.None, new string('0', 64)));
        Assert.False(SecureTransport.AcceptCertificate(null, SslPolicyErrors.None, pin));
        using var handler = SecureTransport.Handler(pin);
        Assert.False(handler.AllowAutoRedirect);
        Assert.False(handler.UseProxy);
        Assert.True(handler.CheckCertificateRevocationList);
    }

    [Fact]
    public void InvalidFingerprintFailsBeforeNetworkUse() =>
        Assert.Throws<InvalidOperationException>(() => SecureTransport.Handler("not-a-fingerprint"));
}
