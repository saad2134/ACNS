/**
 * pages/LeaderboardPage.js
 * ---------------------------------------------------------------
 * Fetches leaderboard from GET /leaderboard and renders it.
 * ---------------------------------------------------------------
 */

import React, { useEffect, useState } from 'react';
import Leaderboard from '../components/Leaderboard';
import { getLeaderboard } from '../services/api';

const LeaderboardPage = () => {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const result = await getLeaderboard();
        console.log('Leaderboard result:', result);
        // Normalise: accept both { leaderboard: [...] } and raw array
        const list = Array.isArray(result) ? result : (result && result.leaderboard) ? result.leaderboard : [];
        setData(list);
      } catch (err) {
        console.error('Failed to load leaderboard:', err);
        setData([]);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  return (
    <div className="page-wrapper">
      <div className="animate-in">
        <h1 className="page-title">🏆 Leaderboard</h1>
        <p className="page-subtitle">
          Top contributors making campus more accessible
        </p>
      </div>

      <div className="row justify-content-center">
        <div className="col-lg-8 col-md-10">
          <Leaderboard data={data} loading={loading} />
        </div>
      </div>
    </div>
  );
};

export default LeaderboardPage;
