/**
 * pages/Home.js
 * ---------------------------------------------------------------
 * Campus Map page (default landing page).
 *
 * • Renders the Mapbox map via <MapView />
 * • Start / Destination dropdowns
 * • "Find Accessible Route" button → POST /route
 * • Quick-access buttons for Report Issue & Leaderboard
 * ---------------------------------------------------------------
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import MapView from '../components/MapView';
import { getRoute, getIssues } from '../services/api';

// Sample campus locations – should match your backend's location vocabulary
const CAMPUS_LOCATIONS = [
  'Arts College',
  'Engineering College',
  'Science College',
  'Administrative Building',
  'University Library',
  'MBA Department',
  'Law College',
  'Sports Complex',
  'Jubilee Hall',
  'Main Gate',
];

const Home = () => {
  const navigate = useNavigate();

  const [start, setStart] = useState('');
  const [destination, setDestination] = useState('');
  const [route, setRoute] = useState(null);
  const [markers, setMarkers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Fetch issues on mount for the map markers
  useEffect(() => {
    const fetchMarkers = async () => {
      try {
        const result = await getIssues();
        const list = Array.isArray(result) ? result : result.issues || [];
        // Map backend issues to MapView marker format { lat, lng, title, type }
        const formattedMarkers = list.map(issue => ({
          lat: issue.location?.latitude || issue.latitude,
          lng: issue.location?.longitude || issue.longitude,
          title: issue.title,
          type: issue.category
        }));
        setMarkers(formattedMarkers);
      } catch (err) {
        console.error("Failed to load map markers:", err);
      }
    };
    fetchMarkers();
  }, []);

  /* --- Request accessible route from backend --- */
  const handleFindRoute = async () => {
    if (!start || !destination) {
      setError('Please select both a start and destination.');
      return;
    }
    if (start === destination) {
      setError('Start and destination cannot be the same.');
      return;
    }

    setLoading(true);
    setError('');
    setRoute(null);

    try {
      const data = await getRoute(start, destination);
      // Expect data.route to be a GeoJSON LineString geometry
      setRoute(data.route || data);
    } catch (err) {
      setError('Unable to fetch route. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-wrapper stagger">
      {/* Header */}
      <div className="animate-in">
        <h1 className="page-title">Campus Map</h1>
        <p className="page-subtitle">Find the most accessible route across campus</p>
      </div>

      {/* Controls */}
      <div
        className="glass-card p-4 mb-4 animate-in"
        style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'flex-end' }}
      >
        {/* Start */}
        <div style={{ flex: '1 1 200px' }}>
          <label className="form-label" style={{ color: 'var(--accent)', fontWeight: 600 }}>
            Start Location
          </label>
          <select
            className="form-acns"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            id="start-location"
          >
            <option value="">— Select —</option>
            {CAMPUS_LOCATIONS.map((loc) => (
              <option key={loc} value={loc}>{loc}</option>
            ))}
          </select>
        </div>

        {/* Destination */}
        <div style={{ flex: '1 1 200px' }}>
          <label className="form-label" style={{ color: 'var(--accent)', fontWeight: 600 }}>
            Destination
          </label>
          <select
            className="form-acns"
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
            id="destination-location"
          >
            <option value="">— Select —</option>
            {CAMPUS_LOCATIONS.map((loc) => (
              <option key={loc} value={loc}>{loc}</option>
            ))}
          </select>
        </div>

        {/* Find Route */}
        <button
          className="btn-acns btn-acns-primary"
          onClick={handleFindRoute}
          disabled={loading}
          id="find-route-btn"
          style={{ flex: '0 0 auto' }}
        >
          {loading ? '⏳ Finding…' : '♿ Find Accessible Route'}
        </button>
      </div>

      {/* Error message */}
      {error && (
        <div
          className="mb-3 p-3 rounded animate-in"
          style={{ background: 'rgba(255,82,82,.12)', color: 'var(--danger)' }}
        >
          {error}
        </div>
      )}

      {/* Map */}
      <div className="animate-in mb-4">
        <MapView route={route} markers={markers} />
      </div>

      {/* Quick-access buttons */}
      <div className="d-flex flex-wrap gap-3 animate-in">
        <button
          className="btn-acns btn-acns-outline"
          onClick={() => navigate('/report')}
          id="goto-report-btn"
        >
          🚧 Report an Issue
        </button>
        <button
          className="btn-acns btn-acns-outline"
          onClick={() => navigate('/leaderboard')}
          id="goto-leaderboard-btn"
        >
          🏆 Leaderboard
        </button>
      </div>
    </div>
  );
};

export default Home;
