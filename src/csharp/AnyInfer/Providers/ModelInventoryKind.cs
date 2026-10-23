namespace AnyInfer.Providers;

/// <summary>Describes the category of model inventory a provider exposes.</summary>
public enum ModelInventoryKind
{
    /// <summary>Models exposed by an already-running engine.</summary>
    Served = 0,

    /// <summary>A catalog of models that could be run.</summary>
    Available = 1,

    /// <summary>A provider-owned on-disk model store.</summary>
    Installed = 2,
}
