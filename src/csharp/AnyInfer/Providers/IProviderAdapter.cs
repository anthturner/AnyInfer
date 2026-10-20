namespace AnyInfer.Providers;

/// <summary>Preserves the legacy generation adapter composition.</summary>
public interface IProviderAdapter : IAsyncDisposable, IGeneratesText
{
}