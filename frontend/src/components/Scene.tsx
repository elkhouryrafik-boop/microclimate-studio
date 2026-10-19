import { useMemo } from 'react';
import { MapView, FlyToInterpolator } from '@deck.gl/core';
import { TileLayer } from '@deck.gl/geo-layers';
import { BitmapLayer, PolygonLayer } from '@deck.gl/layers';
import { LightingEffect, AmbientLight, _SunLight } from '@deck.gl/core';
import DeckGL from '@deck.gl/react';
import type { BuildingPart, Results } from '../api';
import { jetColor } from '../catalog/analyses';

interface SceneProps {
  latitude: number;
  longitude: number;
  buildings: BuildingPart[] | null;
  results: Results | null;
}

export default function Scene({ latitude, longitude, buildings, results }: SceneProps) {
  const lighting = useMemo(() => new LightingEffect({
    ambient: new AmbientLight({ color: [255, 255, 255], intensity: 1.0 }),
    sun: new _SunLight({ timestamp: Date.UTC(2026, 5, 21, 12, 0), color: [255, 255, 255], intensity: 1.4, _shadow: true }),
  }), []);

  const buildingData = useMemo(() => {
    if (!buildings) return [];
    return buildings.map((b, i) => ({
      polygon: b.polygon.map(([lon, lat]) => [lon, lat]),
      height: b.height,
      id: i,
    }));
  }, [buildings]);

  const heatmapImage = useMemo(() => {
    if (!results?.heatmap?.imageUrl) return null;
    return results.heatmap.imageUrl;
  }, [results]);

  const heatmapBounds = results?.heatmap?.bounds;
  const half = 0.0018;

  const layers = [
    new TileLayer({
      id: 'basemap',
      data: 'https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}@2x.png',
      tileSize: 256,
      getPolygonOffset: () => [0, 0],
      renderSubLayers: (props: any) => new BitmapLayer(props, {
        data: undefined,
        image: props.data,
        bounds: props.tile.bbox as [number, number, number, number],
      }),
    }),
  ];

  if (buildings && buildingData.length > 0) {
    layers.push(
      new PolygonLayer({
        id: 'buildings',
        data: buildingData,
        extruded: true,
        getPolygon: (d: any) => d.polygon,
        getElevation: (d: any) => d.height,
        getFillColor: () => [200, 200, 200, 230],
        getLineColor: () => [100, 100, 100, 200],
        stroked: true,
        filled: true,
        wireframe: false,
        getPolygonOffset: () => [0, -100],
      }) as any,
    );
  }

  if (heatmapImage && heatmapBounds) {
    layers.push(
      new BitmapLayer({
        id: 'heatmap',
        image: heatmapImage,
        bounds: [heatmapBounds[0][0], heatmapBounds[0][1], heatmapBounds[1][0], heatmapBounds[1][1]],
        opacity: 0.75 as unknown as number,
        pickable: true,
        getPolygonOffset: () => [0, -200],
      }) as any,
    );
  }

  return (
    <div className="relative w-full h-full" style={{ background: 'var(--slate-50)' }}>
      <DeckGL
        layers={layers as any}
        effects={[lighting]}
        views={new MapView({ repeat: true })}
        initialViewState={{
          longitude,
          latitude,
          zoom: 15.5,
          pitch: 45,
          bearing: 0,
          transitionInterpolator: new FlyToInterpolator({ speed: 1.2, curve: 1.4 }),
          transitionDuration: 1200,
        }}
        controller={{ dragPan: true, scrollZoom: true, doubleClickZoom: false }}
        style={{ position: 'absolute', inset: '0' }}
      />
      <div className="absolute right-2 bottom-2 text-[9px]" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>
        (c) OpenStreetMap (c) CARTO
      </div>
    </div>
  );
}
