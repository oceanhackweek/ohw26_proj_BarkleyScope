"""Build a standalone interactive SST map as a single HTML file.

WHY THIS EXISTS ALONGSIDE sst_map_test.py
    sst_map_test.py targets the platform -- marimo + MapLibre, the stack Web_App_test.py
    uses. That stack needs `maplibre` and `anywidget`, which are declared in its script
    header but are not part of this environment by default, and the JupyterLab marimo
    tile rebuilds them in a sandbox on every launch.

    This file needs nothing that is not already installed. It writes one self-contained
    HTML file you can open directly -- no server, no widget kernel, no install -- so the
    SST layer can be seen, clicked and checked today, and shown to someone else by
    sending them a file.

    Both render from the same barkley_sst.cell_polygons() output and the same colour
    ramp, so what you see here is what the platform map will show.

USAGE
    python preview_map.py
"""

import warnings
from pathlib import Path

import folium
import numpy as np
import pandas as pd

import barkley_sst as sst

warnings.filterwarnings('ignore')

HERE = Path(__file__).resolve().parent

# Same basemap Web_App_test.py uses, so this reads like the platform map rather than
# like a different product. Tiles are fetched when the page is opened.
ESRI_OCEAN = ('https://server.arcgisonline.com/ArcGIS/rest/services/'
              'Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}')
ESRI_ATTR = 'Esri — Ocean Basemap'

SITES = {
    'Bamfield':        (48.835, -125.135),
    'Cape Beale':      (48.786, -125.213),
    'Folger Pinnacle': (48.814, -125.281),
}

TRACK_DAYS = 30
TRACK_COLOR = '#f4a261'


def sst_layer(grid, date, show):
    """One toggleable day of SST cells."""
    # clip=True to match what the platform map draws -- see the note in cell_polygons.
    # Without it this preview would paint over the coastline and disagree with the app.
    collection = sst.cell_polygons(grid, date, clip=True)
    group = folium.FeatureGroup(name=f'SST {date}', show=show, overlay=True)

    def style(feature):
        properties = feature['properties']
        return {
            'fillColor': sst.color_for(properties['sst']),
            # Flagged water is drawn faint rather than dropped -- present, visibly not
            # part of the story. See barkley_sst.flag_disconnected.
            'fillOpacity': 0.16 if properties['flagged'] else 0.72,
            'color': '#00000000',
            'weight': 0,
        }

    folium.GeoJson(
        collection,
        style_function=style,
        tooltip=folium.GeoJsonTooltip(
            fields=['sst', 'lat', 'lon', 'flagged'],
            aliases=['°C', 'lat', 'lon', 'unreachable water'],
            sticky=True,
        ),
    ).add_to(group)
    return group


def glider_layer():
    """Real glider tracks for the same window, drawn over the field they check."""
    import sys
    sys.path.insert(0, str(HERE.parent))
    import cproof_glider as cproof

    frame = cproof.read_archive(cproof.REALTIME_ARCHIVE, variables=['temperature'])
    cutoff = frame['time'].max() - pd.Timedelta(days=TRACK_DAYS)
    recent = frame[frame['time'] >= cutoff].sort_values('time')

    group = folium.FeatureGroup(name=f'Glider tracks (last {TRACK_DAYS} days)', show=True)
    for deployment, part in recent.groupby('deployment'):
        # Thin the track: a polyline of 20,000 vertices bloats the file and renders no
        # differently at this zoom.
        part = part.iloc[::10]
        folium.PolyLine(
            list(zip(part['latitude'], part['longitude'])),
            color=TRACK_COLOR, weight=2.5, opacity=0.9,
            tooltip=f'{deployment} — {len(part):,} points',
        ).add_to(group)
    return group, recent


def legend_html(low, high, dates):
    swatches = ''.join(
        f'<span style="display:inline-block;width:26px;height:12px;'
        f'background:{hex_color}"></span>'
        for _, hex_color in sst.THERMAL_STOPS)
    return f"""
    <div style="position:fixed; bottom:22px; left:22px; z-index:9999;
                background:rgba(255,255,255,0.94); padding:10px 12px;
                border:1px solid #999; border-radius:5px; font:12px/1.45 sans-serif;
                max-width:330px">
      <b>Sea surface temperature</b><br>
      {swatches}<br>
      <span style="float:left">{low:.0f} °C</span>
      <span style="float:right">{high:.0f} °C</span><br style="clear:both">
      <div style="margin-top:7px">
        <b>Fixed scale</b> — a colour means the same temperature on every date, so
        switching days shows the water changing, not the legend.<br><br>
        {len(dates)} days, {dates[0]} to {dates[-1]}. Use the layer control (top right)
        to switch. Faint cells are water not reachable from the open Pacific
        (Strait of Georgia, behind Vancouver Island).<br><br>
        <i>{sst.SOURCE_CAVEAT}</i>
      </div>
    </div>
    """


def main():
    grid = sst.read_grid()
    day_list = sst.dates(grid)
    low, high = sst.COLOR_RANGE

    centre = [np.mean(sst.BOX['lat']), np.mean(sst.BOX['lon'])]
    fmap = folium.Map(location=centre, zoom_start=8, tiles=ESRI_OCEAN, attr=ESRI_ATTR)
    fmap.fit_bounds([[sst.BOX['lat'][0], sst.BOX['lon'][0]],
                     [sst.BOX['lat'][1], sst.BOX['lon'][1]]])

    # Newest day visible, the rest available from the layer control. Showing all seven at
    # once would just stack opaque fills on top of each other.
    for date in day_list:
        sst_layer(grid, date, show=(date == day_list[-1])).add_to(fmap)

    tracks, recent = glider_layer()
    tracks.add_to(fmap)

    sites = folium.FeatureGroup(name='Sites', show=True)
    for name, (lat, lon) in SITES.items():
        folium.CircleMarker([lat, lon], radius=5, color='#111111', weight=2,
                            fill=True, fillColor='#ffffff', fillOpacity=1,
                            tooltip=name).add_to(sites)
    sites.add_to(fmap)

    folium.LayerControl(collapsed=False).add_to(fmap)
    fmap.get_root().html.add_child(folium.Element(legend_html(low, high, day_list)))

    out = HERE / 'barkley_sst_map.html'
    fmap.save(str(out))
    size_mb = out.stat().st_size / 1024 / 1024
    print(f'wrote {out.name}  ({size_mb:.1f} MB)')
    print(f'  {len(day_list)} SST days, {recent["deployment"].nunique()} glider deployment(s)')
    return out


if __name__ == '__main__':
    main()
