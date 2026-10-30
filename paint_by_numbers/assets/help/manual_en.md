## Quick start

The program turns a customer's photo into a production package for a paint-by-numbers picture: outlines with numbers, a paint list with container counts, and print files. Everything is computed by classical algorithms on your computer, with no internet and no artificial intelligence.

1. **Open a photo**: the "Open photo…" button (Ctrl+O).
2. **Set the canvas**: width in mm, height (from the photo's proportions or manually).
3. **Choose a mode** and, if needed, the number of colours. For a kit of up to 24 colours keep "Balanced" or "Simple".
4. **Choose paints**: "Starter (150)" or your own catalogue. This is optional, but it is the only way for identical paints to match between orders.
5. **Mark priority zones** (eyes, important details) on the "Photo and zones" tab. Skin and faces are detailed automatically (see "Detail").
6. **Click the big green "Create preview" button** (Ctrl+R). It usually takes 10–40 seconds.
7. **Review the result** on the "Outlines with numbers", "Colours" and "Comparison" tabs and the "Warnings" list.
8. If needed, **fix regions manually** on the "Region editing" tab.
9. Enter the **order number** and click **"Save package…"** (Ctrl+S).

> Until the coverage norm N has been measured, the container count is **approximate**. This is marked in all documents. See "Paints and coverage norm".

## Program window

The divider between the image and the tables below can be **dragged with the mouse**: enlarge the image or the specification as you prefer. The position is remembered. The mouse wheel zooms the image around the cursor. In number fields and drop-down lists the wheel changes the value only when the field is selected (clicked); if the cursor merely passes over a field, the wheel scrolls the panel and changes nothing.

The blocks on the left **collapse when you click their title** (▾/▸), so the panel fits a low window. Which blocks are collapsed is remembered.

**On the left** there are five blocks from top to bottom: 1. Photo, 2. Canvas and mode, 3. Paints, 4. Priority zones, 5. Result.

**On the right** are tabs with images:
- **Photo and zones**: the photo on the canvas and priority zones;
- **Outlines with numbers**: what will be printed on the canvas;
- **Colours**: the picture in paint colours;
- **Region editing**: manual edits;
- **Comparison**: original, coloured picture and outline side by side;
- **Variants**: the result of the best-variant search.

**At the bottom** are three tabs: "Paint specification" (colours, areas, container counts), "Warnings" (what to check) and "Variants".

Settings (size, mode, paints, shop name, print options) are remembered between launches. You can reset them in the "File" menu.

**Interface language.** The language (Ukrainian or English) is chosen at the first launch. To change it later, use "File → Language". The program will offer to restart to apply the change. The manual follows the interface language.

## Photo and canvas

- Common image formats are supported (JPEG, PNG, etc.). EXIF orientation is respected.
- **Width** and **height** set the size of the finished canvas in mm. The "height from photo proportions" option calculates the height itself. If you set different proportions, the photo will be **cropped** at the edges (warning IMG_CROPPED).
- A large canvas needs a photo of sufficient resolution. If it is too low, the program warns you (IMG_LOW_RES): the outlines will be less accurate.
- As a rule of thumb: the larger the canvas, the more small details the picture can convey, but the more paint containers are needed.

## Modes and number of colours

| Mode | Default colours | Min. region area | Min. width | Digit | Resolution |
|---|---|---|---|---|---|
| 1. Draft | 12 | 40 mm² | 4 mm | 2.8 mm | 3 px/mm |
| 2. Simple | 16 | 25 mm² | 3 mm | 2.5 mm | 3 px/mm |
| 3. Medium | 20 | 17 mm² | 2.5 mm | 2.35 mm | 3 px/mm |
| 4. Balanced | 24 | 12 mm² | 2 mm | 2.2 mm | 3 px/mm |
| 5. Fine | 30 | 8.5 mm² | 1.7 mm | 2.1 mm | 3.5 px/mm |
| 6. Detailed | 36 | 6 mm² | 1.5 mm | 2.0 mm | 4 px/mm |
| 7. Maximum | 44 | 3.5 mm² | 1.2 mm | 1.8 mm | 5 px/mm |

The higher the level, the smaller the regions and digits, the longer the calculation (level 7 takes about twice as long as level 4) and the harder the painting. For a commercial kit limited to 24 colours keep the colour count at 24 and raise only the level. The "Detail" field below merely fine-tunes the chosen level.

These are starting values that still need to be refined by physical tests on real canvases.

The number of colours can be set manually (clear the "number of colours by mode" checkbox). Fewer colours make the kit cheaper and the painting easier, but the picture less faithful. For a commercial kit we aim for **at most 24 colours**, preferably fewer.

The actual number of colours in the picture may be lower than requested: small regions merge into neighbours and extra colours disappear (informational warning COLORS_REDUCED).

### Detail

The "Detail" field (0.5–3) makes regions and digits smaller: at 1.4 a portrait has roughly 50% more regions. Digits never become smaller than 1.6 mm. Always check the legibility of the smallest digits with a test print. The "automatically detail face and skin" checkbox adds colours and smaller regions wherever the program sees skin colour (by colour only, with no face recognition).

## Paints and coverage norm

### Paint stock (catalogue)
A catalogue is a JSON file with a list of paints (code, name, colour). Buttons in the "3. Paints" block:
- **"Starter (150)"**: a built-in **draft** stock palette of 150 colours (8 skin tones, neutrals, muted warm and cool colours, natural colours). At most 24 colours from it go into a kit, the best ones for the particular photo. These are screen colours, **not real paints**. Replace it once you have chosen a supplier.
- **"Catalogue…"**: load your own file. Example format: `examples/catalog_sample.json`.
- **"Reset"**: work without a catalogue (paints get codes P-001, P-002…).

**Without a catalogue** the colours are computed from the photo itself (k-means in Lab space): there are exactly as many as the mode or your manual setting says (12–44; some may disappear when small regions merge), and the codes P-001, P-002… merely number them. Such colours are closer to the photo than a catalogue but do not correspond to real paints.

With a catalogue the program picks the best colours for this photo **directly from the stock** (no more than the requested number) and paints with exactly those. Identical codes in different orders mean the same paint, so a combined purchase list can be made for a batch.

### How many containers
Each container is 3 ml. For a colour with area S you need:

`containers = max(1, round up(S × K / N))`

- **N** ("Coverage N per container") is the area in mm² covered by one 3 ml container. There is no built-in value; it must be **measured by a physical test**: paint a known area and see how much paint was used.
- **K** ("Reserve factor") is a margin for layers, losses and unevenness. The starting value 1.3 is a hypothesis.
- The **"norm N confirmed by physical tests"** checkbox: tick it only after such a measurement. Until then all documents are marked "APPROXIMATE CALCULATION", and the container count is not shown to the buyer.

A large region gets **several containers of the same colour**: this is always so, there is no separate setting.

## Priority zones

Zones are areas of the photo where more detail should be kept (face, eyes, hands). Inside a zone the program uses more colours, smooths less and merges fewer small regions.

On the "Photo and zones" tab choose a tool:
- **Hand**: move the image (wheel zooms, double click fits to window);
- **Pointer**: select and edit a zone (drag the zone itself, its handles or vertices; Delete removes it);
- **Rectangle, ellipse, polygon**: draw a new zone. A polygon is finished with a right click.

In the "4. Priority zones" block you can set the zone's **name** and **weight** (0.1 to 10; a higher value means more detail: smoothing is lighter in the zone, regions can be much smaller, and numbers of small regions are moved out onto leader lines). Zones can be saved to a file and loaded from a file. The "↶ Undo" and "↷ Redo" buttons (Ctrl+Z, Ctrl+Y) revert zone changes.

Tip: for a portrait, one elliptical zone on the face with weight 2–3 is enough. Too many zones with a large weight can produce very small regions.

## Warnings

After creating the preview open the "Warnings" tab. Severity: **critical** (production files are blocked), **normal** (check), **informational**.

| Code | Meaning | What to do |
|---|---|---|
| GEO_TOPOLOGY (critical) | Outlines have gaps or overlaps | Repeat with other settings |
| NUM_NO_ROOM (critical) | There is a region without a number | Fewer colours or the "Simple" mode |
| SPEC_AREA_MISMATCH (critical) | The sum of colour areas differs from the canvas area | Tell the developer |
| AREA_NARROW | Some regions are narrower than the minimum | Usually acceptable; look at those places |
| AREA_SMALL | There are very small regions | Check whether they are important details (eyes) |
| SPEC_PROVISIONAL | Norm N is not confirmed | Measure N and tick the checkbox |
| SPEC_MANY_CONTAINERS | A colour needs more than 10 containers | Check the specification |
| CAT_FAR | No close paint in the catalogue for a colour | Add a paint to the catalogue |
| CAT_TOO_SMALL | The catalogue has fewer paints than colours | Fewer colours or a wider catalogue |
| ZONE_EMPTY, ZONE_NUM_NO_ROOM | Problem with a priority zone | Check the zone's position or weight |
| IMG_LOW_RES | The photo is too small for this canvas | Use a better-quality photo |
| IMG_CROPPED (informational) | The photo was cropped to the canvas proportions | Check the framing |
| NUM_LEADER (informational) | A number was moved out of its region on a leader line | Check legibility |
| COLORS_REDUCED, PRIORITY_ZONES_NOT_SET | Informational messages | No action |

Critical warnings block the production files (print, specification, assembly sheet): only the preview, the project and the report are saved. It is best to fix the cause. If you have checked the layout manually, after saving the program offers to create the files despite the errors.

## Manual editing of regions

The "Region editing" tab appears after the preview is created. Tools:
- **Change colour**: a click on a region assigns it the colour chosen in the "Colour" list. The list contains the kit's colours and (with a catalogue) other stock colours. Neighbouring regions of the same colour merge automatically.
- **Merge with neighbour**: click a region (it turns pink), then click a neighbouring one. Non-adjacent regions cannot be merged.
- **Smooth region**: click a region. Its outline becomes smoother, and small teeth and specks disappear. The "Strength" field (1–25) sets the radius: start with 3 and increase for a stronger effect. If the outline is already smooth, the program reports that nothing changed.
- **Replace colour everywhere**: click a region, then ALL regions of the same colour receive the colour chosen in the list. This is how you edit the palette of a finished picture: replace one paint with another (from the stock; they are in the list marked "+") or merge two colours into one. A colour that no longer remains disappears from the specification.
- **Fill polygon**: click points around the desired area, a right click (or Enter or a double click) finishes, Esc cancels. The area receives the chosen colour: this way you can split a region or fix an outline.
- **Hand**: move and zoom.

### Changing a palette colour

After the preview is created you can change a **single palette colour** of the picture: in the "Paint specification" table double-click a row (or right click → "Change palette colour…"). In the window choose a paint from the stock (with search by code or name) or "Custom colour…". All regions of that colour in the picture get the new colour, and the outlines do not change. If the chosen colour already exists in the palette, the two colours merge. For a colour that is not in the catalogue the program picks the nearest paint and may show a warning about a large difference. The change can be undone (Ctrl+Z on the "Region editing" tab).

Ctrl+Z and Ctrl+Y on this tab undo and redo **region edits** (up to 30 steps). After every edit the outlines, numbers and specification are recalculated in 1–3 seconds.

A new preview discards manual edits (the program asks for confirmation). A saved package contains the edited segmentation.

## How to get the best result

1. **Photo.** Sharp, not heavily blurred, evenly lit; the face should take up a noticeable part of the frame. The higher the resolution, the better (the IMG_LOW_RES warning means too low).
2. **Paints.** Work with the stock catalogue ("Starter (150)" or your own). The program will pick up to 24 best colours from it for this photo.
3. **Detail.** Start with the "Balanced" mode and detail 1.0. If the face looks too simplified, raise detail to 1.2–1.5 and check the digits on a test print.
4. **Priority zones.** Mark eyes, lips and other important details: they get more colours and smaller regions.
5. **Editing.** After the preview fix the small things by hand: smooth a ragged outline, merge a tiny region, replace a colour everywhere.
6. **Checking.** Look at the "Comparison" tab and the "Warnings" list before saving the package.

> A colour on screen is not the colour of the real paint. Check the final palette with swatches of real paints.

## Best variant selection

The "Find best variant" button tries modes and colour counts (up to 9 variants, a few minutes), scores each by similarity to the photo and ease of painting, and picks the best one. The result is shown on the "Variants" tab. A double click on a row applies the variant.

The score is a formula with hypotheses, not the truth: a difference of hundredths means "practically the same". Look at the pictures themselves too.

## Saving the package

"Save package…" creates the folder `order_NUMBER`:

- `source/`: the original photo;
- `project/`: settings and segmentation (so you can return to the order);
- `preview/`: the preview, a **mock-up for the client** (`client_preview.pdf`, `client_before_after.png`);
- `print/`: `canvas_outline.svg` and `.pdf` (outline with numbers 1:1) and, if enabled, `print_ready/`;
- `palette/`: `paint_list.csv`, `palette.png`;
- `production/`: paint specification (PDF and JSON) and the **kit assembly sheet** (`assembly_sheet.pdf`);
- `quality/`: quality report and warnings.

The fields "Order number", "Project name" and "Shop name" go into the documents. **Note:** if a folder with that number already exists, it will be replaced by the new package without asking, so change the order number for each new order.

## Opening a project

"Open project (order folder)…" (Ctrl+Shift+O) restores a saved order: settings, zones, paints, manual edits and the result, without a full recalculation (a few seconds). You can open either the `order_…` folder or the `project/project.json` file.

## Batch processing

"Batch processing (many photos)…" (Ctrl+B) processes many photos in a row:
- **Source**: a folder of photos or a CSV manifest (file; number; name; size; mode; colours; zones);
- **Result**: where to save the orders;
- **Order numbers**: from the file name or sequential (with a prefix and a start number);
- "skip orders that are already done", "find best variant" (slower), number of processes.

Settings are taken from the main window. For zones of a particular photo put a file `photo_name.zones.json` next to it.

After batch processing the result folder contains:
- `batch_report.csv`: a summary for every photo;
- `orders_journal.xlsx`: the **orders journal** and statistics of stock colour usage (which colours are rarely needed and which constantly);
- `purchase_list.xlsx`, `.pdf`, `.csv`: the **combined purchase list** (how many containers of each paint are needed for the whole batch). It is built only for orders with a paint catalogue.

## Print on demand

The "Print options…" button opens the settings. When printing is enabled the package contains `print/print_ready/`:
- a 1:1 PDF with **bleed**, a margin for the **wrap around the stretcher frame**, cut marks and a service line;
- a raster (TIFF or PNG) with the chosen resolution;
- a split into **A4/A3/A2 sheets** with overlap, an assembly diagram and marks.

The bleed and wrap margin are white. Parameters depend on the print shop or printer: ask them for the required bleed and file format.

## Hotkeys

| Action | Keys |
|---|---|
| Open photo | Ctrl+O |
| Open project | Ctrl+Shift+O |
| Create preview | Ctrl+R |
| Save package | Ctrl+S |
| Batch processing | Ctrl+B |
| Undo / redo (zones or region edits depending on the tab) | Ctrl+Z / Ctrl+Y |
| Fit image to window | 0, Home or double click |
| Delete selected zone | Delete |
| Finish polygon | right click, Enter or double click |
| Cancel drawing | Esc |
| This manual | F1 |

## FAQ

**Why is the container count approximate?** Because the coverage norm N has not been measured yet. Measure it and tick "norm N confirmed".

**Numbers do not fit in small regions.** The program moves the number out on a leader line or merges the region with a neighbour. If there are too many leaders, reduce the number of colours or choose the "Simple" mode.

**The picture looks "flat".** Increase the number of colours (up to 24) and detail (1.2–1.5), mark a zone on the eyes and lips, and make sure the catalogue has enough skin tones.

**The face is simplified while the background is too fine.** The background can be smoothed with the "Smooth region" tool, and the face additionally marked with a priority zone. The "automatically detail face and skin" checkbox must be on.

**The paint colour is not what is needed.** On the "Region editing" tab the "Replace colour everywhere" tool replaces one palette colour with another (from the stock).

**The divider between the image and the table does not move.** Hover over the thin strip between them (the cursor changes) and drag.

**Too many colours for the kit.** Reduce the number of colours. With a catalogue the program will choose the best 12–24 from your stock.

**The "Save package…" button is unavailable.** Create a preview first. Any change of settings discards the preview.

**A critical warning blocks the package.** Fix the cause (see the warnings table) and create the preview again. Creating files despite errors is possible only after a manual check of the layout.

**The program does not start or shows an error.** Save the error text and contact the developer.

## Glossary

- **Region**: a closed area of one colour with one number.
- **Leader**: a line from a number placed nearby to a small region.
- **Catalogue**: the list of paints in your shop (the stock).
- **ΔE2000**: a measure of difference between two colours; up to 2 the difference is barely noticeable, above 5 it is noticeable.
- **N, K**: the coverage norm of one container and the reserve factor (see "Paints and coverage norm").
- **Project**: a saved order folder you can return to.
- **Bleed**: a margin beyond the trim line that is printed so no white strip remains after cutting.
- **Wrap**: the part of the canvas that wraps around the stretcher frame.
- **Program author**: reeperetter.
