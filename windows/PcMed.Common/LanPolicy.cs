using System.Buffers.Binary;
using System.Net;
using System.Net.Sockets;

namespace PcMed.Common;

public static class LanPolicy
{
    public static bool Contains(string cidr, IPAddress? address)
    {
        if (address is null) return false;
        if (address.IsIPv4MappedToIPv6) address = address.MapToIPv4();
        var parts = cidr.Split('/');
        if (parts.Length != 2 || !IPAddress.TryParse(parts[0], out var network) || network.AddressFamily != AddressFamily.InterNetwork ||
            address.AddressFamily != AddressFamily.InterNetwork || !int.TryParse(parts[1], out var prefix) || prefix is < 1 or > 30)
            return false;
        var mask = uint.MaxValue << (32 - prefix);
        var bytes = network.GetAddressBytes();
        if (!(bytes[0] == 10 && prefix >= 8 || bytes[0] == 172 && bytes[1] is >= 16 and <= 31 && prefix >= 12 ||
              bytes[0] == 192 && bytes[1] == 168 && prefix >= 16)) return false;
        var networkNumber = BinaryPrimitives.ReadUInt32BigEndian(network.GetAddressBytes());
        return (networkNumber & mask) == networkNumber &&
            (BinaryPrimitives.ReadUInt32BigEndian(address.GetAddressBytes()) & mask) == networkNumber;
    }
}
