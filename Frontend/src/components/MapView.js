import React, { useEffect, useRef } from 'react';

const MapView = ({ route = null, markers = [] }) => {
  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const routeLayerRef = useRef(null);
  const markerLayersRef = useRef([]);

  // Initialize map once Leaflet is available
  const initMap = () => {
    if (!mapContainerRef.current || mapRef.current) return;
    const L = window.L;
    if (!L) return;

    const map = L.map(mapContainerRef.current, {
      center: [35.2058, -97.4457], // OU Campus
      zoom: 15,
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors',
      maxZoom: 19,
    }).addTo(map);

    mapRef.current = map;
  };

  // Load Leaflet CSS and JS from CDN, then init map
  useEffect(() => {
    if (window.L) {
      initMap();
      return;
    }

    if (!document.getElementById('leaflet-css')) {
      const css = document.createElement('link');
      css.id = 'leaflet-css';
      css.rel = 'stylesheet';
      css.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
      document.head.appendChild(css);
    }

    if (!document.getElementById('leaflet-js')) {
      const script = document.createElement('script');
      script.id = 'leaflet-js';
      script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
      script.onload = () => initMap();
      document.body.appendChild(script);
    } else {
      // Script tag exists but may still be loading
      const existingScript = document.getElementById('leaflet-js');
      existingScript.addEventListener('load', () => initMap());
    }

    return () => {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  }, []); // eslint-disable-line

  // Draw route whenever it changes
  useEffect(() => {
    const map = mapRef.current;
    const L = window.L;
    if (!map || !L) return;

    // Remove old route
    if (routeLayerRef.current) {
      map.removeLayer(routeLayerRef.current);
      routeLayerRef.current = null;
    }

    if (route && route.coordinates && route.coordinates.length > 1) {
      // GeoJSON coords are [lon, lat], Leaflet wants [lat, lon]
      const latlngs = route.coordinates.map(c => [c[1], c[0]]);
      routeLayerRef.current = L.polyline(latlngs, {
        color: '#00d4ff',
        weight: 6,
        opacity: 0.9,
      }).addTo(map);
      map.fitBounds(routeLayerRef.current.getBounds(), { padding: [40, 40] });
    }
  }, [route]);

  // Draw markers whenever they change
  useEffect(() => {
    const map = mapRef.current;
    const L = window.L;
    if (!map || !L) return;

    markerLayersRef.current.forEach(m => map.removeLayer(m));
    markerLayersRef.current = [];

    markers.forEach(m => {
      const marker = L.circleMarker([m.lat, m.lng], {
        radius: 8,
        fillColor: '#ff5252',
        color: '#fff',
        weight: 2,
        fillOpacity: 0.9,
      })
        .bindPopup(`<b>${m.title || 'Issue'}</b><br/>${m.type || ''}`)
        .addTo(map);
      markerLayersRef.current.push(marker);
    });
  }, [markers]);

  return (
    <div
      ref={mapContainerRef}
      style={{
        width: '100%',
        height: '420px',
        borderRadius: '12px',
        overflow: 'hidden',
        border: '1px solid rgba(0,212,255,0.3)',
        background: '#1a1a2e',
      }}
    />
  );
};

export default MapView;
