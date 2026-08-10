# Demo app UI fixes

This plan collects visual and rendering issues found by code review and by capturing the running PySide6 demo app. Items are grouped by severity; each entry names the file(s) involved and the concrete change to make.

## How this was checked

- Ran the demo with `./workspace demo --reset` under `QT_QPA_PLATFORM=xcb`.
- Captured the main window with `xwd`/`ffmpeg` and rendered individual widgets to PNG via `QWidget.grab()`.
- Walked the widget code in `src/demo_app/` and the QSS in `src/demo_app/theme.py`.

## Confirmed rendering bugs

### 1. Composer does not grow when text wraps

**File:** [src/demo_app/widgets/composer.py](src/demo_app/widgets/composer.py)

`_AutoGrowingTextEdit._adjust_height()` computes height from `document().blockCount()`. Because `QPlainTextEdit` wraps by default, a single long paragraph still has `blockCount() == 1` even when it occupies several visual lines. The composer stays one line tall and clips wrapped text.

**Reproduction:** resize the window narrow and paste a long sentence into the message box.

**Fix:** base the height on the actual laid-out document height (e.g. `document().size().height()` or the number of visible line layouts) instead of `blockCount()`. Cap at `_MAX_LINES` by computing the pixel height of that many lines.

### 2. `HintText` widgets are unstyled

**Files:**
- [src/demo_app/widgets/app_settings_dialog.py](src/demo_app/widgets/app_settings_dialog.py)
- [src/demo_app/widgets/add_model_dialog.py](src/demo_app/widgets/add_model_dialog.py)
- [src/demo_app/widgets/models_dialog.py](src/demo_app/widgets/models_dialog.py)

Several hint/secondary labels use `setObjectName("HintText")`, but `src/demo_app/theme.py` has no rule for `QLabel#HintText`. They fall back to the default label color, so explanatory text looks identical to body text.

**Fix:** add `QLabel#HintText { color: $muted; font-size: 9pt; }` to the stylesheet.

### 3. Markdown can fail to render and fall back to escaped plain text

**File:** [src/demo_app/widgets/markdown_renderer.py](src/demo_app/widgets/markdown_renderer.py)

`render_markdown()` wraps the Markdown output in `<root>...</root>` and parses it with `xml.etree.ElementTree`. Python-Markdown emits plain HTML (`<hr>`, `&nbsp;`, unclosed `<img>` tags, etc.) that is often not well-formed XML. When `ET.fromstring` fails, the whole message is shown as escaped preformatted text.

**Fix:** run the sanitizer on an HTML parser that tolerates HTML constructs, e.g. `html.parser` + `BeautifulSoup` (if adding a dependency is acceptable) or Python's `html.parser` with a small allow-list traversal. At minimum, pre-process void tags and common entities before the XML parse.

### 4. Message body sets an explicit font that may fight the stylesheet

**File:** [src/demo_app/widgets/chat_view.py](src/demo_app/widgets/chat_view.py)

`MessageBubble` calls `self._body.setFont(QFont("Segoe UI", 10))`. The application stylesheet already sets `font-family: "Segoe UI", sans-serif; font-size: 10pt;` on `QWidget`. The explicit `QFont` can override or confuse theme changes, and on Linux where "Segoe UI" is absent it may pick a different fallback than the stylesheet's `sans-serif`.

**Fix:** remove the explicit `setFont` call and rely on the stylesheet.

### 5. Welcome cards may have uneven heights

**File:** [src/demo_app/widgets/chat_view.py](src/demo_app/widgets/chat_view.py)

`_WelcomeCard` has `setFixedWidth(190)` but no fixed or minimum height. Cards with different title/description lengths will wrap to different heights and sit in the same row, producing a ragged bottom edge.

**Fix:** either give all cards a shared minimum height tall enough for the longest expected text, or make the card layout align them by top and let them share the same height via a size policy / layout constraint.

### 6. Request-options grid is cramped at small widths

**File:** [src/demo_app/main_window.py](src/demo_app/main_window.py)

The sampling/routing grid has five equally-stretched columns. On the default 1280×860 window (or narrower) the spin boxes, combo boxes, and their labels compete for space, and the rightmost "Routing help" chip can look orphaned.

**Fix:**
- Reduce the number of columns (e.g. three columns of two rows) so controls have more horizontal room.
- Or give less stretch to columns that only contain a small help chip / checkbox.
- Set sensible minimum widths for `QDoubleSpinBox` and `QSpinBox` so their contents do not clip.

### 7. Inspector splitter minimizes target/tools sections to 40 px

**File:** [src/demo_app/main_window.py](src/demo_app/main_window.py)

`self._inspector_splitter.setSizes([280, 280, 220, 40, 40])` collapses the Target and Tools sections to 40 pixels. `CollapsibleSection.HEADER_HEIGHT` is 32 px plus a 1 px border, so the header can be clipped at that size.

**Fix:** use `CollapsibleSection.HEADER_HEIGHT` (or `HEADER_HEIGHT + 4`) as the minimized size instead of a magic 40 px, and import it rather than duplicating the value.

### 8. Tab close button has no explicit size

**File:** [src/demo_app/widgets/chat_tabs.py](src/demo_app/widgets/chat_tabs.py)

The per-tab close button is created with no `setFixedSize`; only the 12×12 icon is set. The hit target depends on the platform style and may be uncomfortably small.

**Fix:** set `button.setFixedSize(20, 20)` and `button.setIconSize(QSize(12, 12))`.

### 9. Custom tab pane outline can misalign

**File:** [src/demo_app/widgets/tab_widget.py](src/demo_app/widgets/tab_widget.py)

`_TabbedPaneOutline.paintEvent()` reads `self._tabs.tabBar().geometry().bottom()` to draw the top border. If the tab bar geometry has not been updated yet (e.g. during a theme change, resize, or tab move animation), the outline can be drawn at the wrong vertical position, leaving a gap or overdraw.

**Fix:** schedule the outline update with a single-shot 0 ms timer after tab moves/resizes, or clamp `top` to a sensible minimum and ensure the outline widget is always the same size as the tab widget.

## Visual polish

### 10. Notice bars blend into the transcript

**File:** [src/demo_app/widgets/chat_view.py](src/demo_app/widgets/chat_view.py)

`add_notice()` creates a `QLabel` with `NoticeBar` style (italic, muted color) but no background or border. Mid-conversation status notices can be mistaken for assistant text.

**Fix:** add a subtle pill/badge style for `QLabel#NoticeBar`, e.g. a recessed background (`$surface`) with a left accent border, and reduce the font size slightly.

### 11. Required-field asterisk is hardcoded red

**File:** [src/demo_app/widgets/settings_dialog.py](src/demo_app/widgets/settings_dialog.py)

`_REQUIRED_MARK` uses inline color `#d13438`. This color does not adapt to custom themes and may clash (e.g. on the "rose" theme).

**Fix:** use the theme's `danger` token (`theme.color("danger")`) when constructing the label, or style a `Required` pseudo-class in the stylesheet.

### 12. Engine/model dropdowns do not elide long model names

**File:** [src/demo_app/widgets/engine_bar.py](src/demo_app/widgets/engine_bar.py)

The model combo box displays `f"{model.id} — {size}"` strings. With long identifiers the text can overflow the combo width and be truncated by Qt with an ellipsis, but there is no tooltip or size hint adjustment, so users cannot see the full name.

**Fix:** set the item tooltip to the full model string and/or configure the combo box popup to be wider (`self._model.setMinimumContentsLength(…)` and `setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)`).

### 13. Telemetry card event text lacks left alignment

**File:** [src/demo_app/widgets/telemetry_view.py](src/demo_app/widgets/telemetry_view.py)

Each event line is a `QLabel` with a severity badge and details. The badge is part of the rich-text string, so wrapping lines restart at the left margin under the badge rather than being indented to align with the detail text.

**Fix:** use a small two-column layout per event (badge label + detail label) so wrapped detail lines stay aligned.

### 14. Model dialog hardware cards use hardcoded `color: white`

**File:** [src/demo_app/widgets/models_dialog.py](src/demo_app/widgets/models_dialog.py)

`_HardwareCard.set_data()` applies `color: white` to the vendor mark. On the light custom themes this is correct because the mark background is a dark brand color, but the rule is not theme-aware. If a future theme gives the mark a light background, the text could become invisible.

**Fix:** compute mark text color from the accent luminance (use Qt to check whether white or `$on_accent` has better contrast), or at least document the assumption.

### 15. No minimum window size

**File:** [src/demo_app/main_window.py](src/demo_app/main_window.py)

`MainWindow` calls `self.resize(1280, 860)` but never `setMinimumSize(...))`). Users can shrink the window below a usable width and clip the engine bar, inspector, and request options.

**Fix:** add `self.setMinimumSize(960, 640)` (or similar) so the layout never compresses below usability.

## Suggested implementation order

1. Fix composer auto-grow (#1) — this is the most obvious functional bug.
2. Add `HintText` style (#2) — one-line stylesheet change, high visual impact.
3. Harden Markdown rendering (#3) — prevents assistant messages from appearing broken.
4. Remove explicit `setFont` in message body (#4) and set tab close button size (#8).
5. Improve request-options grid (#6), inspector minimized sizes (#7), and window minimum size (#15).
6. Polish notice bars (#10), telemetry alignment (#13), and required asterisk (#11).

## Files touched

- `src/demo_app/widgets/composer.py`
- `src/demo_app/theme.py`
- `src/demo_app/widgets/markdown_renderer.py`
- `src/demo_app/widgets/chat_view.py`
- `src/demo_app/main_window.py`
- `src/demo_app/widgets/chat_tabs.py`
- `src/demo_app/widgets/tab_widget.py`
- `src/demo_app/widgets/app_settings_dialog.py`
- `src/demo_app/widgets/add_model_dialog.py`
- `src/demo_app/widgets/models_dialog.py`
- `src/demo_app/widgets/settings_dialog.py`
- `src/demo_app/widgets/telemetry_view.py`
- `src/demo_app/widgets/engine_bar.py`
