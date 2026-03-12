import React from 'react';
import { Link } from 'react-router-dom';

function NotFound() {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '80vh',
      textAlign: 'center',
      padding: 20,
      background: '#1a1a2e',
      color: '#fff'
    }}>
      <h1 style={{ fontSize: '6rem', margin: 0, color: '#00d4ff' }}>404</h1>
      <h2 style={{ color: '#90a4ae' }}>Page Not Found</h2>
      <p style={{ color: '#90a4ae', marginTop: 10 }}>
        The page you're looking for doesn't exist or has been moved.
      </p>
      <Link to="/" style={{
        marginTop: 20,
        padding: '12px 24px',
        background: '#00d4ff',
        color: '#000',
        textDecoration: 'none',
        borderRadius: 8,
        fontWeight: 600
      }}>
        Go Home
      </Link>
    </div>
  );
}

export default NotFound;
