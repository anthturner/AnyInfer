"""A provider settings dialog with no provider-specific code in it.

Every widget in this file is built by reading a
`ProviderSetupSpec` off a descriptor. There is no ``if provider ==
"openai"`` anywhere, which is the whole claim being demonstrated: install a third-party
adapter that advertises itself through the ``anyinfer.providers`` entry-point group and it
shows up here, correctly rendered, without this file changing.

The dialog configures *instances*, not engines. An engine can be added more than once —
two Azure tenants, a local and a remote Ollama, and each instance carries an editable
alias that becomes its id in a ``alias:model`` target. Only engines the user actually
added appear; the registry is offered through a searchable dropdown instead of as a
checklist of everything installed.

The mapping from `SetupFieldKind` to widget is the only knowledge
the UI needs:

===================  =========================================================
Field kind           Rendered as
===================  =========================================================
``endpoint``         Line edit, with host-shorthand expansion hinted
``secret``           Password-masked line edit
``api-version``      Line edit
``model-list``       Editable combo box, populated by discovery when available
``reasoning-efforts``Combo box over the normalized effort levels
``choice``           Combo box over the field's declared ``choices``
``path``             Line edit with a file picker
``directory``        Line edit with a directory picker
``host-profile``     Line edit
``text``             Line edit
===================  =========================================================

The last four are what stop a field being rendered as something it is not. Before they
existed a llama.cpp model *directory* was declared an ``endpoint``, and this file — having
nothing else to go on — offered it the example value an endpoint deserves: ``https://…``.
The lesson generalizes past that one field: a UI cannot recover semantics the descriptor
did not state, so the fix belongs in the kind, not in a special case here.

Everything *else* about a field comes from the descriptor rather than from this file: the
example value in an empty editor is the field's own ``placeholder`` (guessing it here
would stamp one provider's environment-variable convention onto all the others), a
mandatory field is marked with a red asterisk from its ``required`` flag, and a provider
that accepts a *choice* of credential declares that as an ``any_of`` group with a
``requirement_note`` explaining it.

Fields are also split by *prominence*, not just by kind. A provider marks the fields it
already has a standard value for as ``advanced``, and those go behind a disclosure rather
than into the form: an Ollama instance asks nothing at all, and an OpenAI one asks for a
key rather than for a key, a base URL, and a version. The disclosure still opens on its
own whenever a stored setting overrides one of those values, because the alternative —
hiding a setting that is in force — trades one confusion for a worse one.
"""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from anyinfer.providers.base import ProviderAdapter
from anyinfer.providers.base import ProviderConfig as ProviderAdapterConfig
from anyinfer.registry import ProviderDescriptor, ProviderRegistry, SetupField

from .. import theme
from ..config import DemoConfig, ProviderConfig
from .icons import themed_icon

__all__ = ["ProviderSettingsDialog"]

_REASONING_EFFORTS = ("", "minimal", "low", "medium", "high")


def _required_mark() -> str:
    """Render the required marker from the active theme's danger token."""
    return f"<span style='color:{theme.color('danger')};'>*</span>"


def _field_label(setup_field: SetupField) -> QLabel:
    """Build a field's label, marking it when the provider declares it required."""
    label = QLabel(
        f"{setup_field.label} {_required_mark()}" if setup_field.required else setup_field.label
    )
    label.setTextFormat(Qt.TextFormat.RichText)
    if setup_field.required:
        # The colour alone is not an accessible signal, so say it where a screen reader
        # and a hover both reach.
        label.setAccessibleName(f"{setup_field.label}, required")
        label.setToolTip("Required")
    return label


def unique_alias(preferred: str, taken: set[str]) -> str:
    """Return ``preferred``, or the first ``preferred-N`` that is not already taken.

    Adding an engine twice must not silently collide, and must not refuse either: the
    second instance gets a distinct default the user is free to rename.
    """
    if preferred not in taken:
        return preferred
    suffix = 2
    while f"{preferred}-{suffix}" in taken:
        suffix += 1
    return f"{preferred}-{suffix}"


class _PathField(QWidget):
    """A line edit for a filesystem location, with a picker beside it.

    Typing stays possible — a path may not exist yet, and ``llama-server`` resolved off
    PATH is a bare name rather than a location at all, so the browser fills the editor
    instead of replacing it.
    """

    def __init__(self, setup_field: SetupField, current: str, placeholder: str) -> None:
        super().__init__()
        self._directory = setup_field.kind == "directory"
        self._label = setup_field.label

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._edit = QLineEdit(current)
        self._edit.setPlaceholderText(placeholder)
        self._edit.setAccessibleName(setup_field.label)
        layout.addWidget(self._edit, 1)

        browse = QPushButton("Browse…")
        browse.setAccessibleName(f"Browse for {setup_field.label}")
        browse.setAutoDefault(False)
        browse.setDefault(False)
        browse.clicked.connect(self._on_browse)
        layout.addWidget(browse)

    def text(self) -> str:
        """The path as typed or picked."""
        return self._edit.text()

    def setToolTip(self, tip: str) -> None:  # noqa: N802 — Qt's spelling
        """Put the field's help on the editor as well as the container.

        A tooltip on a composite widget is easy to miss, since the cursor spends its time
        over the child that accepts text rather than over the layout around it.
        """
        super().setToolTip(tip)
        self._edit.setToolTip(tip)

    def _on_browse(self) -> None:
        start = self._edit.text().strip()
        if self._directory:
            chosen = QFileDialog.getExistingDirectory(self, f"Choose {self._label}", start)
        else:
            chosen, _ = QFileDialog.getOpenFileName(self, f"Choose {self._label}", start)
        if chosen:
            self._edit.setText(chosen)


class _AdvancedFields(QWidget):
    """A disclosure holding the fields a provider already has a standard value for.

    Collapsed, it is one line; expanded, it is an ordinary form. The point is not to
    hide anything — every field is still reachable and still saved, but to keep the
    question a user is being asked ("what is your API key?") from arriving alongside four
    settings that are already correct.
    """

    def __init__(self, fields: list[tuple[SetupField, QLabel, QWidget]]) -> None:
        super().__init__()
        self._editors = {f.key: editor for f, _, editor in fields}
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        count = len(fields)
        self._toggle = QPushButton(
            f"Advanced — {count} standard {'value' if count == 1 else 'values'}"
        )
        self._toggle.setObjectName("DisclosureButton")
        self._toggle.setFlat(True)
        self._toggle.setIconSize(QSize(14, 14))
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.setToolTip(
            "These already have working values. Change them only for a proxy, a mirror, "
            "or a non-standard deployment."
        )
        self._toggle.setAutoDefault(False)
        self._toggle.setDefault(False)
        self._toggle.clicked.connect(self.toggle_expanded)
        # Left-aligned like a link rather than centred like a command button.
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._toggle)
        row.addStretch(1)
        layout.addLayout(row)

        self._body = QWidget()
        body_layout = QFormLayout(self._body)
        body_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        body_layout.setContentsMargins(16, 8, 8, 8)
        body_layout.setSpacing(8)
        for _, label, editor in fields:
            body_layout.addRow(label, editor)
        self._body.setVisible(False)
        layout.addWidget(self._body)

        self._update_toggle()

    @property
    def editors(self) -> dict[str, QWidget]:
        """The editors this section owns, keyed by setup-field key."""
        return dict(self._editors)

    @property
    def expanded(self) -> bool:
        """Whether the fields are currently shown."""
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        """Show or hide the advanced fields."""
        self._expanded = expanded
        self._body.setVisible(expanded)
        self._update_toggle()

    def toggle_expanded(self) -> None:
        """Flip the disclosure."""
        self.set_expanded(not self._expanded)

    def reapply_theme(self) -> None:
        """Re-render the chevron for the current palette."""
        self._update_toggle()

    def _update_toggle(self) -> None:
        name = "chevron-down" if self._expanded else "chevron-right"
        self._toggle.setIcon(themed_icon(self._toggle, name, size=14))
        state = "Hide" if self._expanded else "Show"
        self._toggle.setAccessibleName(f"{state} advanced settings")


class _ProviderPanel(QWidget):
    """One instance's setup fields, rendered from its engine's setup spec.

    Deliberately just the *fields*: enabling, alias editing, and deletion belong to the
    row that owns this panel, so the same field-rendering logic serves every instance of
    every engine without knowing which.
    """

    def __init__(self, descriptor: ProviderDescriptor, config: ProviderConfig) -> None:
        super().__init__()
        self._descriptor = descriptor
        self._editors: dict[str, QWidget] = {}
        # The dialog has no editor for the free-form options mapping; carry it through
        # unchanged so a save round-trip never silently drops it.
        self._options = dict(config.options)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        layout = self._form = QFormLayout()
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        outer.addLayout(layout)

        locality = "local engine" if descriptor.locality == "local" else "hosted provider"
        subtitle = QLabel(f"<i>{locality} — engine <code>{descriptor.id}</code></i>")
        subtitle.setTextFormat(Qt.TextFormat.RichText)
        layout.addRow(subtitle)

        setup = descriptor.setup
        for setup_field in setup.essential_fields:
            label, editor = self._build_field(setup_field, config.values)
            self._editors[setup_field.key] = editor
            layout.addRow(label, editor)

        if not setup.fields:
            layout.addRow(QLabel("<i>No configuration required.</i>"))
        elif not setup.essential_fields:
            # Every field this engine has already has a standard value, so there is
            # nothing to ask. Say so, rather than showing a form that looks unfinished.
            layout.addRow(
                QLabel("<i>Nothing to fill in — this engine runs on its standard settings.</i>")
            )

        if setup.requirement_note:
            note = QLabel(f"<i>{_required_mark()} {setup.requirement_note}</i>")
            note.setTextFormat(Qt.TextFormat.RichText)
            note.setWordWrap(True)
            layout.addRow(note)

        if setup.host_shorthand is not None:
            shorthand = setup.host_shorthand
            layout.addRow(
                QLabel(
                    f"<i>A bare hostname expands to "
                    f"{shorthand.scheme}://&lt;host&gt;:{shorthand.default_port}</i>"
                )
            )

        self._advanced: _AdvancedFields | None = None
        if setup.advanced_fields:
            self._advanced = _AdvancedFields(
                [(f, *self._build_field(f, config.values)) for f in setup.advanced_fields]
            )
            self._editors.update(self._advanced.editors)
            outer.addWidget(self._advanced)
            # An override already in force must not be hidden: a saved value here is the
            # one case where the standard settings are *not* what this instance uses.
            if any(config.values.get(f.key, "").strip() for f in setup.advanced_fields):
                self._advanced.set_expanded(True)

    def _build_field(
        self, setup_field: SetupField, values: Mapping[str, str]
    ) -> tuple[QLabel, QWidget]:
        """Render one field according to its declared kind."""
        current = values.get(setup_field.key, "")
        editor: QWidget

        if setup_field.kind == "reasoning-efforts":
            combo = QComboBox()
            combo.addItems(_REASONING_EFFORTS)
            combo.setCurrentText(current)
            editor = combo
        elif setup_field.kind == "choice":
            combo = QComboBox()
            # A leading blank is the "use the default" entry: a bounded set still has to
            # be leaveable, or saving would force a value onto a field the provider is
            # perfectly able to answer itself.
            combo.addItem("")
            combo.addItems(setup_field.choices)
            combo.setCurrentText(current)
            editor = combo
        elif setup_field.kind == "model-list":
            combo = QComboBox()
            combo.setEditable(True)
            combo.setCurrentText(current)
            editor = combo
        elif setup_field.kind in ("path", "directory"):
            editor = _PathField(setup_field, current, self._placeholder_for(setup_field))
        else:
            line = QLineEdit(current)
            if setup_field.kind == "secret":
                line.setEchoMode(QLineEdit.EchoMode.Password)
            line.setPlaceholderText(self._placeholder_for(setup_field))
            editor = line

        tooltip = self._tooltip_for(setup_field)
        if tooltip:
            editor.setToolTip(tooltip)

        return _field_label(setup_field), editor

    def _tooltip_for(self, setup_field: SetupField) -> str:
        """The field's help text, with the value it falls back to when left blank.

        Stating the standard value is what makes an empty editor readable: blank means
        "use this", not "unset". It is only appended when the provider declared a
        `SetupField.default_value` — a field with no default has nothing honest to say
        here, and inventing one would be a guess presented as a fact.
        """
        parts = [setup_field.help_text] if setup_field.help_text else []
        if setup_field.default_value:
            parts.append(f"Left blank, this uses {setup_field.default_value}.")
        return " ".join(parts)

    def _placeholder_for(self, setup_field: SetupField) -> str:
        """The example value to show in an empty editor.

        The provider's own `SetupField.placeholder` wins, because only it knows which
        environment variable its credential conventionally lives in, and its declared
        `SetupField.default_value` comes next since a field with a default has a better
        thing to show than an example: what will actually happen. The remaining fallbacks
        are deliberately generic — a kind-level default that named one provider's
        convention would be wrong for every other provider that shares the kind.

        The endpoint fallback is the descriptor's *own* base URL, and only for the field
        that holds one. It used to apply to every ``endpoint``-kind field, which is how a
        model directory came to suggest an HTTPS URL; the kinds now separate those, and
        the key check keeps a third-party descriptor that still conflates them from
        reintroducing the same nonsense.
        """
        if setup_field.placeholder:
            return setup_field.placeholder
        if setup_field.default_value:
            return setup_field.default_value
        if setup_field.kind == "secret":
            # A literal is accepted but never written to disk (see anyinfer_demo.config), so
            # the placeholder says which of the two survives a restart rather than
            # presenting them as equivalent.
            return "env://VARIABLE_NAME — a literal key works but is session-only"
        if setup_field.kind == "endpoint" and setup_field.key == "base_url":
            return self._descriptor.default_base_url or "https://…"
        return ""

    def values(self) -> dict[str, str]:
        """Current field values, keyed by setup-field key."""
        result: dict[str, str] = {}
        for key, editor in self._editors.items():
            if isinstance(editor, QComboBox):
                result[key] = editor.currentText().strip()
            elif isinstance(editor, QLineEdit | _PathField):
                result[key] = editor.text().strip()
        return result

    def missing_required(self) -> list[str]:
        """Labels of unsatisfied requirements, so the dialog can refuse to save.

        Covers both kinds the setup spec can express: fields that are individually
        required, and ``any_of`` groups where a provider accepts a choice of credential
        and needs one of them. A group is reported as its alternatives joined by "or",
        so the message names what would satisfy it rather than just what is absent.
        """
        setup = self._descriptor.setup
        values = self.values()
        missing = [f.label for f in setup.fields if f.required and not values.get(f.key)]
        missing.extend(
            " or ".join(setup.label_for(key) for key in group)
            for group in setup.unsatisfied_groups(values)
        )
        return missing

    @property
    def options(self) -> dict[str, object]:
        """The options mapping this panel carries through untouched."""
        return dict(self._options)

    @property
    def advanced_section(self) -> _AdvancedFields | None:
        """The disclosure holding this engine's standard-value fields, if it has any."""
        return self._advanced

    def reapply_theme(self) -> None:
        """Re-render themed chrome inside the panel after a palette change."""
        if self._advanced is not None:
            self._advanced.reapply_theme()


class _ConfiguredEngineRow(QFrame):
    """One configured instance: header (alias, engine, delete) plus expandable detail."""

    delete_requested = Signal(object)
    alias_changed = Signal()

    def __init__(self, descriptor: ProviderDescriptor, config: ProviderConfig) -> None:
        super().__init__()
        self._descriptor = descriptor
        self.setObjectName("ProviderCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)

        self._expander = QPushButton()
        self._expander.setObjectName("IconButton")
        self._expander.setFixedSize(24, 24)
        self._expander.setIconSize(QSize(16, 16))
        self._expander.setAccessibleName(f"Expand {descriptor.display_name} settings")
        self._expander.setToolTip("Show or hide this engine's setup fields.")
        self._expander.clicked.connect(self.toggle_expanded)
        header.addWidget(self._expander)

        self._enabled = QCheckBox()
        self._enabled.setChecked(config.enabled)
        self._enabled.setAccessibleName(f"Enable {descriptor.display_name}")
        self._enabled.setToolTip("Enabled engines appear in the engine picker.")
        header.addWidget(self._enabled)

        name = QLabel(f"<b>{descriptor.display_name}</b>")
        name.setTextFormat(Qt.TextFormat.RichText)
        header.addWidget(name)

        header.addWidget(QLabel("Alias:"))
        self._alias = QLineEdit(config.instance_id)
        self._alias.setPlaceholderText(descriptor.id)
        self._alias.setAccessibleName(f"Alias for {descriptor.display_name}")
        self._alias.setToolTip(
            "This instance's id, as used in a target string. Rename it to configure the "
            "same engine more than once."
        )
        self._alias.textChanged.connect(lambda *_: self.alias_changed.emit())
        header.addWidget(self._alias, 1)

        self._delete = QPushButton()
        self._delete.setObjectName("IconButton")
        self._delete.setFixedSize(28, 28)
        self._delete.setIconSize(QSize(16, 16))
        self._delete.setAccessibleName(f"Remove {descriptor.display_name}")
        self._delete.setToolTip("Remove this engine from the configured list.")
        self._delete.clicked.connect(lambda: self.delete_requested.emit(self))
        header.addWidget(self._delete)

        outer.addLayout(header)

        self._panel = _ProviderPanel(descriptor, config)
        outer.addWidget(self._panel)

        # A freshly added engine opens expanded (there is something to fill in); a row
        # restored from saved settings starts collapsed, which is what keeps a long list
        # scannable.
        self._expanded = True
        self.set_expanded(not config.values and not config.enabled)
        self.reapply_theme()

    # ---- state -----------------------------------------------------------------------

    @property
    def descriptor(self) -> ProviderDescriptor:
        """The engine this row configures an instance of."""
        return self._descriptor

    def alias(self) -> str:
        """The instance id the user typed, stripped."""
        return self._alias.text().strip()

    def is_enabled(self) -> bool:
        """Whether this instance is turned on."""
        return self._enabled.isChecked()

    def missing_required(self) -> list[str]:
        """Labels of required fields left empty."""
        return self._panel.missing_required()

    def set_expanded(self, expanded: bool) -> None:
        """Show or hide the setup fields."""
        self._expanded = expanded
        self._panel.setVisible(expanded)
        self.reapply_theme()

    def toggle_expanded(self) -> None:
        """Flip the detail area's visibility."""
        self.set_expanded(not self._expanded)

    def reapply_theme(self) -> None:
        """Re-render the themed icons for the current palette and expansion state."""
        self._expander.setIcon(
            themed_icon(
                self._expander,
                "chevron-down" if self._expanded else "chevron-right",
                size=16,
            )
        )
        self._delete.setIcon(themed_icon(self._delete, "trash", size=16))
        self._panel.reapply_theme()

    @property
    def advanced_section(self) -> _AdvancedFields | None:
        """This row's advanced-settings disclosure, if its engine declares one."""
        return self._panel.advanced_section

    def focus_alias(self) -> None:
        """Put the cursor in the alias field, ready for renaming."""
        self._alias.setFocus()
        self._alias.selectAll()

    def to_config(self) -> ProviderConfig:
        """This row's state as a `ProviderConfig`, preserving the options mapping."""
        alias = self.alias()
        return ProviderConfig(
            provider_id=self._descriptor.id,
            alias=alias if alias != self._descriptor.id else None,
            enabled=self.is_enabled(),
            values=self._panel.values(),
            options=self._panel.options,
        )


class ProviderSettingsDialog(QDialog):
    """Add, configure, and remove provider instances.

    Nothing here knows which providers exist: the dropdown is the registry, and each
    row's fields are its engine's declared setup spec.
    """

    def __init__(
        self,
        registry: ProviderRegistry,
        config: DemoConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Provider settings")
        self.setMinimumSize(620, 520)
        self._registry = registry
        self._config = config
        self._rows: list[_ConfiguredEngineRow] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        intro = QLabel(
            "Add an engine, then fill in the fields it declares. Every field below is "
            "generated from the provider's <code>ProviderSetupSpec</code> — this dialog "
            "contains no per-provider code. Add an engine twice to configure two "
            "instances of it, each with its own alias."
        )
        intro.setObjectName("Caption")
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(intro)

        outer.addLayout(self._build_add_row())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self._list_layout = QVBoxLayout(container)
        self._list_layout.setContentsMargins(4, 4, 4, 4)
        self._list_layout.setSpacing(10)
        self._empty = QLabel("<i>No engines configured yet — pick one above and choose Add.</i>")
        self._empty.setTextFormat(Qt.TextFormat.RichText)
        self._list_layout.addWidget(self._empty)
        self._list_layout.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

        self._error = QLabel()
        self._error.setObjectName("ErrorText")  # colored by the application stylesheet
        self._error.setWordWrap(True)
        outer.addWidget(self._error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        for provider in config.providers:
            self._add_row(provider)
        self._refresh_empty_state()

    # ---- construction ----------------------------------------------------------------

    def _build_add_row(self) -> QHBoxLayout:
        """The searchable engine dropdown and its Add button."""
        row = QHBoxLayout()
        row.addWidget(QLabel("Add engine:"))

        self._engines = QComboBox()
        self._engines.setEditable(True)
        self._engines.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._engines.setAccessibleName("Engine to add")
        self._engines.setToolTip(
            "Every registered provider, including third-party ones. Type to filter."
        )
        for descriptor in sorted(self._registry, key=lambda d: d.display_name.lower()):
            # A derived descriptor is another instance's identity, not an engine anyone
            # should add a *new* instance of — offer only real engines.
            if descriptor.derived_from is None:
                self._engines.addItem(descriptor.display_name, descriptor.id)

        completer = self._engines.completer()
        if completer is not None:
            completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        # Enter in the dropdown adds, matching the Add button.
        line = self._engines.lineEdit()
        if line is not None:
            line.returnPressed.connect(self._on_add_clicked)
        row.addWidget(self._engines, 1)

        add = QPushButton("Add")
        add.setAccessibleName("Add engine")
        add.setDefault(False)
        add.setAutoDefault(False)
        add.clicked.connect(self._on_add_clicked)
        row.addWidget(add)
        return row

    def _on_add_clicked(self) -> None:
        """Add the engine named in the dropdown, by data or by typed display name."""
        descriptor = self._selected_descriptor()
        if descriptor is None:
            self._error.setText(f"No engine matches {self._engines.currentText().strip()!r}.")
            return
        self._error.clear()
        alias = unique_alias(descriptor.id, {row.alias() for row in self._rows})
        row = self._add_row(
            ProviderConfig(
                provider_id=descriptor.id,
                alias=alias if alias != descriptor.id else None,
                enabled=True,
            )
        )
        self._refresh_empty_state()
        row.set_expanded(True)
        if alias != descriptor.id:
            # The auto-suffixed alias is a guess; put the cursor there so renaming it is
            # the obvious next keystroke rather than a discovery.
            row.focus_alias()

    def _selected_descriptor(self) -> ProviderDescriptor | None:
        """Resolve the dropdown's current state to a descriptor, if it names one."""
        text = self._engines.currentText().strip()
        index = self._engines.findText(text)
        if index >= 0:
            data = self._engines.itemData(index)
            if isinstance(data, str):
                return self._registry.get(data)
        if text and self._registry.has(text):
            return self._registry.get(text)
        return None

    def _add_row(self, config: ProviderConfig) -> _ConfiguredEngineRow:
        """Insert a configured-instance row for one provider configuration."""
        descriptor = self._descriptor_for(config)
        row = _ConfiguredEngineRow(descriptor, config)
        row.delete_requested.connect(self._on_delete_row)
        row.alias_changed.connect(self._error.clear)
        # Before the trailing stretch, so rows stay top-aligned.
        self._list_layout.insertWidget(self._list_layout.count() - 1, row)
        self._rows.append(row)
        return row

    def _descriptor_for(self, config: ProviderConfig) -> ProviderDescriptor:
        """The engine descriptor behind one configuration.

        A configuration naming an engine that is no longer installed still has to render
        — dropping it silently would delete the user's settings on the next save, so it
        falls back to a minimal stand-in that declares no fields.
        """
        if self._registry.has(config.provider_id):
            descriptor = self._registry.get(config.provider_id)
            if descriptor.derived_from is None:
                return descriptor
            # A descriptor derived by a previous client run: report the engine it came
            # from, so the row shows the engine rather than an instance of an instance.
            if self._registry.has(descriptor.derived_from):
                return self._registry.get(descriptor.derived_from)
            return descriptor
        return ProviderDescriptor(
            id=config.provider_id,
            display_name=f"{config.provider_id} (not installed)",
            factory=_uninstalled_factory,
        )

    def _on_delete_row(self, row: object) -> None:
        """Remove one configured instance."""
        if not isinstance(row, _ConfiguredEngineRow):
            return
        self._rows.remove(row)
        self._list_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._error.clear()
        self._refresh_empty_state()

    def _refresh_empty_state(self) -> None:
        self._empty.setVisible(not self._rows)

    # ---- save ------------------------------------------------------------------------

    def _on_accept(self) -> None:
        """Validate aliases and required fields before accepting, so errors surface here."""
        problem = self._validate()
        if problem:
            self._error.setText(problem)
            return
        self.accept()

    def _validate(self) -> str:
        """The first problem preventing a save, or an empty string when there is none."""
        seen: set[str] = set()
        for row in self._rows:
            alias = row.alias()
            if not alias:
                row.focus_alias()
                return (
                    f"{row.descriptor.display_name}: the alias is empty. Every configured "
                    "engine needs an id."
                )
            if alias in seen:
                row.focus_alias()
                return f"Alias {alias!r} is used twice — each engine needs a unique alias."
            seen.add(alias)

        missing = [
            f"{row.alias()}: {', '.join(row.missing_required())}"
            for row in self._rows
            if row.is_enabled() and row.missing_required()
        ]
        if missing:
            for row in self._rows:
                if row.is_enabled() and row.missing_required():
                    row.set_expanded(True)
            return "Required fields are empty — " + "; ".join(missing)
        return ""

    def result_config(self) -> DemoConfig:
        """The configuration the user assembled.

        Built by replacement rather than merge: the list is the whole truth about which
        instances exist, so a deleted row has to disappear from the result.
        """
        return self._config.with_providers([row.to_config() for row in self._rows])


def _uninstalled_factory(config: ProviderAdapterConfig) -> ProviderAdapter:
    """Stand-in factory for a configuration whose provider is not installed.

    Never called: the descriptor exists only so the dialog can render and re-save the
    stored settings of a provider that has gone away.
    """
    raise RuntimeError(f"provider {config.provider_id!r} is not installed")
