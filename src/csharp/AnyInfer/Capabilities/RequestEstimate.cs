namespace AnyInfer.Capabilities;

/// <summary>Breaks a request's estimated input size into independently auditable components.</summary>
public sealed record RequestEstimate
{
    /// <summary>Initializes an immutable request-size estimate.</summary>
    public RequestEstimate(
        TokenEstimate messages,
        TokenEstimate tools,
        TokenEstimate schema,
        TokenEstimate? envelope = null,
        long unpricedParts = 0)
    {
        Messages = messages ?? throw new ArgumentNullException(nameof(messages));
        Tools = tools ?? throw new ArgumentNullException(nameof(tools));
        Schema = schema ?? throw new ArgumentNullException(nameof(schema));
        Envelope = envelope ?? new TokenEstimate(0, 0);
        UnpricedParts = unpricedParts;
    }

    /// <summary>Gets conversation and message-envelope estimates.</summary>
    public TokenEstimate Messages { get; }

    /// <summary>Gets offered-tool estimates.</summary>
    public TokenEstimate Tools { get; }

    /// <summary>Gets structured-schema estimates.</summary>
    public TokenEstimate Schema { get; }

    /// <summary>Gets provider transport-envelope planning estimates.</summary>
    public TokenEstimate Envelope { get; }

    /// <summary>Gets the number of content parts for which no faithful native estimate exists.</summary>
    public long UnpricedParts { get; }

    /// <summary>Gets the checked total planning estimate.</summary>
    public long Tokens => checked(checked(Messages.Tokens + Tools.Tokens) + checked(Schema.Tokens + Envelope.Tokens));

    /// <summary>Gets the checked total lower-bound estimate.</summary>
    public long Floor => checked(checked(Messages.Floor + Tools.Floor) + checked(Schema.Floor + Envelope.Floor));
}
