# Paralives Theme Notes

Last reviewed: 2026-05-25

Sources:
- https://paralives.wiki/mods
- https://paralives.wiki/simulator
- https://paralives.wiki/updates
- https://www.paralives.com/

## Direction

Paralives reads as cozy, creative, and approachable rather than glossy or high-tech. The fan wiki turns that into a playful pastel UI, while the official site leans on large game screenshots, a white hand-lettered logo, dark image overlays, and restrained uppercase navigation. A future theme should combine both: soft, optimistic life-sim colors with enough dark ink and official screenshot texture to keep it grounded.

## Palette

Primary base:
- Cream background: `#fff9f4`
- Main ink: `#2a3832`
- Muted ink: `#5c6e66`
- Official dark brown/footer: `#3c342f`
- Deep image overlay: `#0f0606`
- White logo/text on image: `#ffffff`

Greens:
- Brand/meta green: `#5a8f6e`
- Sage: `#5cb88a`
- Sage dark: `#3d8f66`
- Mint: `#b8e8d4`
- Mint deep: `#6b9b7b`

Warm accents:
- Peach: `#ffdac1`
- Peach deep: `#ffb89a`
- Lemon: `#fff3a0`
- Coral: `#ff7b6b`
- Coral deep: `#e85a48`
- Official warm link/gold: `#d88518`

Cool/playful accents:
- Sky: `#9ee0f5`
- Sky deep: `#5bc4e8`
- Lavender: `#d4c4f5`
- Lavender deep: `#a78bfa`

Observed screenshot colors from official assets, useful for imagery-led sections:
- Bright sky/water cyan around `#40c0e0`
- Soft cloud/sea mist around `#c0e0e0`
- Cliff/building warmth around `#e0c080` and `#c0a080`
- Dense foliage around `#206040`, `#206020`, `#406020`
- Warm human/brick tones around `#e0c0a0` and `#c08060`
- Suit/shadow ink around `#202020`

## UI Traits

Wiki:
- Translucent cream sticky header with peach bottom border and a sage-tinted shadow.
- Rounded pill navigation; active and hover states use peach fill, coral border, and coral-deep text.
- Page heroes use soft gradients plus a subtle white grid overlay.
- Mods hero: lavender to lavender-deep to peach.
- Simulator hero: sky-deep to lavender to mint.
- Updates hero: coral to peach to sky.
- Cards use white surfaces, thick pale borders, soft lifted shadows, and slight hover motion.
- Buttons are pill-shaped, bold, playful, and slightly bouncy.
- Section labels are small uppercase dashed pills.
- Decorative language includes blobs, dashed circles, soft gradients, and icon badges.

Official site:
- Image-first, full-bleed presentation with large in-game screenshots carrying much of the color.
- White hand-lettered logo on dark/image backgrounds.
- Typography is cleaner and more editorial: Futura-style uppercase headings/nav, Proxima-style body.
- Black/dark overlays make screenshots readable without making the brand feel severe.
- Visual mood from screenshots: sunny skies, soft clouds, sage greenery, warm stone/stucco, cozy interiors, and saturated garden florals.

## Future Theme Guidance

Use cream and sage as the everyday shell, coral for primary action, sky/lavender/peach as rotating section accents, and dark brown/near-black only for immersive hero/footer moments. Do not make the product feel all-green; the charm comes from the full pastel set.

Prefer rounded, soft UI, but keep application surfaces disciplined if this theme is applied to the current file-sharing app. A good compromise is `8px` to `12px` for operational cards, pill buttons/chips where appropriate, and larger radius only for decorative or marketing surfaces.

Typography should avoid literal Comic Sans in production. Use a friendly rounded display face or system fallbacks such as Trebuchet/Segoe for headings, with a clean body font. Reserve hand-drawn treatment for the wordmark or a few expressive labels.

Keep contrast practical: body text should stay ink on cream or white on dark/image overlays. Pastels should mostly be backgrounds, badges, borders, and highlights, not small text colors.

## Starter Tokens

```css
:root {
  --para-cream: #fff9f4;
  --para-ink: #2a3832;
  --para-muted: #5c6e66;
  --para-sage: #5cb88a;
  --para-sage-dark: #3d8f66;
  --para-mint: #b8e8d4;
  --para-peach: #ffdac1;
  --para-coral: #ff7b6b;
  --para-coral-dark: #e85a48;
  --para-sky: #9ee0f5;
  --para-sky-dark: #5bc4e8;
  --para-lavender: #d4c4f5;
  --para-lavender-dark: #a78bfa;
  --para-lemon: #fff3a0;
  --para-official-dark: #3c342f;
  --para-overlay: #0f0606;
  --para-link-gold: #d88518;
}
```
