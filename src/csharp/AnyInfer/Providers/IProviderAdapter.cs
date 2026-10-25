namespace AnyInfer.Providers;

/// <summary>Preserves the legacy generation adapter composition.</summary>
/// <remarks>
/// Combines <see cref="IGeneratesText"/> with <see cref="IAsyncDisposable"/>. A client that adopts an adapter
/// disposes it when the client is disposed.
/// </remarks>
public interface IProviderAdapter : IAsyncDisposable, IGeneratesText
{
}