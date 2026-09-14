import os
import zlib
import struct

icon_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "icons")
os.makedirs(icon_dir, exist_ok=True)

# 1. Create Vector SVG icons (Scalable to any resolution)
svg_content = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="100%" height="100%">
  <defs>
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0B0F19"/>
      <stop offset="50%" stop-color="#0F172A"/>
      <stop offset="100%" stop-color="#0284C7"/>
    </linearGradient>
    <linearGradient id="shieldGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#06B6D4"/>
      <stop offset="100%" stop-color="#3B82F6"/>
    </linearGradient>
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="8" stdDeviation="16" flood-color="#06B6D4" flood-opacity="0.45"/>
    </filter>
  </defs>
  
  <!-- Outer Squircle Body -->
  <rect width="512" height="512" rx="112" fill="url(#bgGrad)" />
  <rect width="504" height="504" x="4" y="4" rx="108" fill="none" stroke="rgba(255,255,255,0.15)" stroke-width="3" />
  <rect width="500" height="500" x="6" y="6" rx="106" fill="none" stroke="#06B6D4" stroke-width="1.5" stroke-opacity="0.4" />

  <!-- Background Radar / Pulse Waves -->
  <circle cx="256" cy="256" r="180" fill="none" stroke="#06B6D4" stroke-width="2" stroke-opacity="0.25" stroke-dasharray="8 8" />
  <circle cx="256" cy="256" r="130" fill="none" stroke="#3B82F6" stroke-width="2.5" stroke-opacity="0.3" />

  <!-- Center Hexagon / Shield -->
  <polygon points="256,105 380,180 380,332 256,407 132,332 132,180" fill="url(#shieldGrad)" filter="url(#glow)" />
  <polygon points="256,115 370,186 370,326 256,397 142,326 142,186" fill="#0B132B" opacity="0.88" />

  <!-- Radio Antenna / Signal Waves -->
  <path d="M 200 210 A 70 70 0 0 1 312 210" fill="none" stroke="#38BDF8" stroke-width="7" stroke-linecap="round"/>
  <path d="M 220 230 A 45 45 0 0 1 292 230" fill="none" stroke="#38BDF8" stroke-width="6" stroke-linecap="round"/>

  <!-- Core Pulsing Node -->
  <circle cx="256" cy="256" r="16" fill="#06B6D4" filter="url(#glow)"/>
  <circle cx="256" cy="256" r="8" fill="#FFFFFF"/>

  <!-- Text "CCO" or Operational Symbol -->
  <text x="256" y="340" font-family="'Plus Jakarta Sans', system-ui, -apple-system, sans-serif" font-size="44" font-weight="900" fill="#FFFFFF" text-anchor="middle" letter-spacing="4">OP</text>
  <text x="256" y="365" font-family="'Plus Jakarta Sans', system-ui, -apple-system, sans-serif" font-size="16" font-weight="800" fill="#38BDF8" text-anchor="middle" letter-spacing="3">CCO ENEL</text>
</svg>"""

with open(os.path.join(icon_dir, "icon.svg"), "w", encoding="utf-8") as f:
    f.write(svg_content)

with open(os.path.join(icon_dir, "favicon.svg"), "w", encoding="utf-8") as f:
    f.write(svg_content)

print("Saved icon.svg and favicon.svg successfully.")

# Helper to create uncompressed valid RGBA PNG
def write_png(filename, width, height, rgba_data):
    def chunk(tag, data):
        return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", zlib.crc32(tag + data) & 0xffffffff)
    
    ihdr = struct.pack("!IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + rgba_data[y * width * 4:(y + 1) * width * 4] for y in range(height))
    idat = zlib.compress(raw, 9)
    
    with open(filename, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", idat))
        f.write(chunk(b"IEND", b""))
    print(f"Saved: {filename} ({width}x{height})")

def generate_solid_app_icon(size, filename, maskable=False):
    # Generates a sleek dark gradient with glowing cyan shield and "OP" emblem
    pixels = bytearray(size * size * 4)
    cx, cy = size / 2.0, size / 2.0
    r_corner = size * 0.22 if not maskable else 0

    for y in range(size):
        for x in range(size):
            idx = (y * size + x) * 4
            
            # Check corner radius for non-maskable
            dx = max(abs(x - cx) - (cx - r_corner), 0)
            dy = max(abs(y - cy) - (cy - r_corner), 0)
            dist_corner = (dx * dx + dy * dy) ** 0.5
            if not maskable and dist_corner > r_corner:
                pixels[idx:idx+4] = b"\x00\x00\x00\x00"
                continue

            # Base gradient (deep slate #0B0F19 to #0F172A to cyan #0284C7 at bottom right)
            fx = x / size
            fy = y / size
            r = int(11 + 10 * fx + 20 * fy)
            g = int(15 + 25 * fx + 60 * fy)
            b = int(25 + 50 * fx + 120 * fy)
            a = 255

            # Distance from center
            d_center = ((x - cx)**2 + (y - cy)**2)**0.5
            norm_d = d_center / (size * 0.5)

            # Circular glow ring
            if 0.60 <= norm_d <= 0.64:
                r, g, b = min(255, r + 40), min(255, g + 160), min(255, b + 200)

            # Center shield region (hexagon)
            q_x = abs(x - cx) / (size * 0.36)
            q_y = abs(y - cy) / (size * 0.40)
            if q_x <= 1.0 and q_y <= 1.0 and (q_x * 0.5 + q_y * 0.866) <= 1.0:
                # Inside hexagon
                if (q_x * 0.5 + q_y * 0.866) >= 0.88 or q_x >= 0.88 or q_y >= 0.88:
                    # Border
                    r, g, b = 6, 182, 212
                else:
                    # Core
                    r, g, b = 15, 23, 42

            # Center circle
            if norm_d <= 0.08:
                r, g, b = 6, 182, 212
            if norm_d <= 0.04:
                r, g, b = 255, 255, 255

            # Rim specular border
            if not maskable and abs(dist_corner - r_corner) < 1.5:
                r, g, b = 140, 220, 245

            pixels[idx] = r
            pixels[idx+1] = g
            pixels[idx+2] = b
            pixels[idx+3] = a

    write_png(filename, size, size, bytes(pixels))

generate_solid_app_icon(192, os.path.join(icon_dir, "icon-192.png"))
generate_solid_app_icon(512, os.path.join(icon_dir, "icon-512.png"))
generate_solid_app_icon(512, os.path.join(icon_dir, "icon-maskable.png"), maskable=True)
generate_solid_app_icon(180, os.path.join(icon_dir, "apple-touch-icon.png"))
