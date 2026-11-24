# tabstrip-revert

- Reverted the transparent/gradient tab strip band: the gradient depended on a pane-width
  variable that did not resolve inside the strip, so the seam moved and the band lost its surface.
- Restored the solid tab surface; the leading 12px corner stays.
