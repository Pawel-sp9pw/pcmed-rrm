using System.Buffers.Binary;
using System.Collections.Concurrent;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Text.Json;
using PcMed.Common;

namespace PcMed.Agent;

public static class GatewayDiscovery
{
    public static bool PrivateAddress(IPAddress address)
    {
        var bytes = address.GetAddressBytes();
        return address.AddressFamily == AddressFamily.InterNetwork &&
            (bytes[0] == 10 || bytes[0] == 172 && bytes[1] is >= 16 and <= 31 || bytes[0] == 192 && bytes[1] == 168);
    }

    public static IPAddress[] Targets(IPAddress address, int prefix)
    {
        if (!PrivateAddress(address) || prefix is < 22 or > 30)
            throw new InvalidOperationException("Discovery is limited to on-link RFC1918 IPv4 subnets /22 through /30 (maximum 1022 hosts). Select a smaller --scan-cidr on larger LANs.");
        var numeric = BinaryPrimitives.ReadUInt32BigEndian(address.GetAddressBytes());
        var network = numeric & (uint.MaxValue << (32 - prefix));
        var size = 1u << (32 - prefix);
        var targets = new List<IPAddress>();
        for (var offset = 1u; offset < size - 1; offset++)
        {
            var bytes = new byte[4];
            BinaryPrimitives.WriteUInt32BigEndian(bytes, network + offset);
            targets.Add(new IPAddress(bytes));
        }
        return targets.ToArray();
    }

    public static IPAddress[] LocalTargets(string? cidr)
    {
        var interfaces = NetworkInterface.GetAllNetworkInterfaces().Where(adapter => adapter.OperationalStatus == OperationalStatus.Up &&
            adapter.NetworkInterfaceType is NetworkInterfaceType.Ethernet or NetworkInterfaceType.Wireless80211);
        var local = interfaces.SelectMany(adapter => adapter.GetIPProperties().UnicastAddresses)
            .Where(address => PrivateAddress(address.Address)).ToArray();
        if (cidr is not null)
        {
            var parts = cidr.Split('/');
            if (parts.Length != 2 || !IPAddress.TryParse(parts[0], out var address) || !int.TryParse(parts[1], out var prefix))
                throw new InvalidOperationException("Use an IPv4 network/prefix for --scan-cidr.");
            var candidates = Targets(address, prefix);
            if (!local.Any(item => item.PrefixLength <= prefix && candidates.Contains(item.Address)))
                throw new InvalidOperationException("The scan must contain this computer's address and be a subset of its local LAN.");
            return candidates;
        }
        var targets = local.SelectMany(address => Targets(address.Address, address.PrefixLength)).Distinct().ToArray();
        if (targets.Length is 0 or > 1022) throw new InvalidOperationException("Select one local LAN using --scan-cidr; automatic discovery is limited to 1022 addresses.");
        return targets;
    }

    public static async Task<string[]> Scan(string fingerprint, int port, string? cidr)
    {
        var expected = SecureTransport.Fingerprint(fingerprint);
        if (port is < 1024 or > 49151) throw new InvalidOperationException("Invalid gateway port.");
        var targets = LocalTargets(cidr);
        using var client = new HttpClient(SecureTransport.Handler(expected)) { Timeout = TimeSpan.FromMilliseconds(1800) };
        var found = new ConcurrentBag<string>();
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(90));
        await Parallel.ForEachAsync(targets, new ParallelOptions { MaxDegreeOfParallelism = 32, CancellationToken = deadline.Token }, async (address, cancellation) =>
        {
            var origin = $"https://{address}:{port}";
            try
            {
                using var probe = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
                probe.CancelAfter(TimeSpan.FromMilliseconds(1800));
                using var response = await client.GetAsync(origin + "/.well-known/pcmed-gateway", HttpCompletionOption.ResponseHeadersRead, probe.Token);
                if (!response.IsSuccessStatusCode || response.Content.Headers.ContentLength is > 2048) return;
                using var body = await response.Content.ReadAsStreamAsync(probe.Token);
                var bytes = new byte[2049];
                var count = 0;
                while (count < bytes.Length)
                {
                    var read = await body.ReadAsync(bytes.AsMemory(count), probe.Token);
                    if (read == 0) break;
                    count += read;
                }
                if (count > 2048) return;
                using var data = JsonDocument.Parse(bytes.AsMemory(0, count));
                if (data.RootElement.GetProperty("service").GetString() == "pcmed-gateway" && data.RootElement.GetProperty("protocol").GetInt32() == 1)
                    found.Add(origin);
            }
            catch (Exception exception) when (exception is HttpRequestException or IOException or OperationCanceledException or JsonException or KeyNotFoundException or InvalidOperationException) { }
        });
        return found.Order(StringComparer.Ordinal).ToArray();
    }
}
