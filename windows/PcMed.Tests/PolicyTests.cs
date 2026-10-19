using System.Text.Json;
using PcMed.Agent;
using PcMed.Common;
using Xunit;

namespace PcMed.Tests;

public sealed class PolicyTests
{
    private static WorkItem Job(string kind, WorkSpec spec) => new(Guid.NewGuid().ToString(), Guid.NewGuid().ToString(), kind, spec, 600);

    [Theory]
    [InlineData("http://central.test")]
    [InlineData("https://user:pass@central.test")]
    [InlineData("https://central.test/admin")]
    public void RejectUnsafeEndpoint(string value) => Assert.Throws<InvalidOperationException>(() => Policy.HttpsEndpoint(value));

    [Theory]
    [InlineData("http://packages.test/file.exe")]
    [InlineData("https://evil.test/file.exe")]
    [InlineData("https://packages.test@evil.test/file.exe")]
    public void RejectUnsafeInstaller(string value) => Assert.Throws<InvalidOperationException>(() => Policy.ArtifactUrl(value, ["packages.test"]));

    [Theory]
    [InlineData("POST", "/api/tenants")]
    [InlineData("GET", "/api/agent/next")]
    [InlineData("POST", "/api/agent/results/../../tenants")]
    [InlineData("POST", "/api/agent/next/extra")]
    public void RelayDoesNotExposeAdministratorRoutes(string method, string path) => Assert.False(Policy.RelayRoute(method, path));

    [Fact]
    public void RelayAllowsOnlyKnownAgentOperations()
    {
        Assert.True(Policy.RelayRoute("POST", "/api/agent/enroll"));
        Assert.True(Policy.RelayRoute("POST", "/api/agent/heartbeat"));
        Assert.True(Policy.RelayRoute("POST", "/api/agent/results/" + Guid.NewGuid()));
    }

    [Fact]
    public void ProcessArgumentsNeverUseShellForInstaller()
    {
        var job = Job("exe", new WorkSpec("https://packages.test/a.exe", new string('a', 64), null, ["/quiet", "value with spaces", "& echo injected"], null, null));
        Policy.Validate(job);
        var start = Executor.StartInfo(job, @"C:\ProgramData\PcMed\payload.exe");
        Assert.False(start.UseShellExecute);
        Assert.Equal(3, start.ArgumentList.Count);
        Assert.Equal("& echo injected", start.ArgumentList[2]);
    }

    [Fact]
    public void ScriptsRequireHashAndRejectExtraArguments()
    {
        Assert.Throws<InvalidOperationException>(() => Policy.Validate(Job("powershell", new WorkSpec(null, null, "echo ok", [], null, null))));
        Assert.Throws<InvalidOperationException>(() => Policy.Validate(Job("bat", new WorkSpec(null, new string('a', 64), "echo ok", ["injection"], null, null))));
    }

    [Fact]
    public void JournalAndApiUseSnakeCaseContract()
    {
        var job = Job("message", new WorkSpec(null, null, null, null, "Title", "Body"));
        var serialized = JsonSerializer.Serialize(new Journal(job, new WorkResult(job.Claim, "unknown", null, "restart")), Wire.Json);
        Assert.Contains("timeout_seconds", serialized);
        Assert.Contains("exit_code", serialized);
        Assert.Equal(job, JsonSerializer.Deserialize<Journal>(serialized, Wire.Json)!.Job);
    }
}
