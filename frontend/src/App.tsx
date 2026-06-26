// TYDZIEN 7
// frontend/src/App.tsx
// Glowny komponent aplikacji Dutch AVM

import React, { useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell
} from 'recharts';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';
const API_KEY = process.env.REACT_APP_API_KEY || 'demo_test_key';

// ==================================================
// TYPY
// ==================================================

interface ValuationRequest {
  postcode: string;
  huisnummer: number;
  oppervlakte_m2: number;
  gebruiksdoel: string;
  energielabel: string;
  bouwjaar?: number;
}

interface SHAPFactor {
  feature: string;
  impact_eur: number;
  direction: string;
}

interface ComparableProperty {
  postcode: string;
  oppervlakte_m2: number;
  energielabel: string | null;
  estimated_price: number;
  price_per_m2: number;
}

interface ValuationResult {
  estimated_value: number;
  confidence_low: number;
  confidence_high: number;
  price_per_m2: number;
  top_factors: SHAPFactor[];
  comparable_properties: ComparableProperty[];
  model_version: string;
  plan: string;
  timestamp: string;
}

// ==================================================
// HELPERS
// ==================================================

const formatEUR = (amount: number): string =>
  new Intl.NumberFormat('nl-NL', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 0,
  }).format(amount);

const ENERGIELABELS = ['A+++', 'A++', 'A+', 'A', 'B', 'C', 'D', 'E', 'F', 'G'];

// ==================================================
// COMPONENTS
// ==================================================

const StatCard: React.FC<{ label: string; value: string; sub?: string }> = ({ label, value, sub }) => (
  <div style={{
    background: '#f8f9fa',
    borderRadius: 12,
    padding: '16px 20px',
    flex: 1,
    minWidth: 0,
  }}>
    <div style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>{label}</div>
    <div style={{ fontSize: 22, fontWeight: 600, color: '#1a1a2e' }}>{value}</div>
    {sub && <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>{sub}</div>}
  </div>
);

const SHAPChart: React.FC<{ factors: SHAPFactor[] }> = ({ factors }) => {
  const data = factors.map(f => ({
    name: f.feature,
    impact: Math.abs(f.impact_eur),
    direction: f.direction,
  }));

  return (
    <div style={{ marginTop: 24 }}>
      <h3 style={{ fontSize: 14, fontWeight: 500, color: '#333', marginBottom: 12 }}>
        Belangrijkste factoren
      </h3>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" tickFormatter={v => `€${(v/1000).toFixed(0)}k`} style={{ fontSize: 11 }} />
          <YAxis type="category" dataKey="name" width={150} style={{ fontSize: 11 }} />
          <Tooltip formatter={(v: number) => formatEUR(v)} />
          <Bar dataKey="impact" radius={[0, 4, 4, 0]}>
            {data.map((entry, i) => (
              <Cell
                key={i}
                fill={entry.direction === 'positive' ? '#1D9E75' : '#D85A30'}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

const ComparableCard: React.FC<{ prop: ComparableProperty }> = ({ prop }) => (
  <div style={{
    border: '0.5px solid #e0e0e0',
    borderRadius: 8,
    padding: '12px 16px',
    flex: 1,
  }}>
    <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 4 }}>{prop.postcode}</div>
    <div style={{ fontSize: 12, color: '#666' }}>
      {prop.oppervlakte_m2} m² · {prop.energielabel || 'N/A'}
    </div>
    <div style={{ fontSize: 16, fontWeight: 600, color: '#1a1a2e', marginTop: 4 }}>
      {formatEUR(prop.estimated_price)}
    </div>
    <div style={{ fontSize: 11, color: '#999' }}>
      {formatEUR(prop.price_per_m2)}/m²
    </div>
  </div>
);

// ==================================================
// MAIN APP
// ==================================================

const App: React.FC = () => {
  const [form, setForm] = useState<ValuationRequest>({
    postcode: '3011AA',
    huisnummer: 42,
    oppervlakte_m2: 85,
    gebruiksdoel: 'wonen',
    energielabel: 'B',
    bouwjaar: 1985,
  });

  const [result, setResult] = useState<ValuationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch(`${API_URL}/v1/valuate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': API_KEY,
        },
        body: JSON.stringify(form),
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || `HTTP ${response.status}`);
      }

      const data: ValuationResult = await response.json();
      setResult(data);

    } catch (err: any) {
      setError(err.message || 'Er is een fout opgetreden');
    } finally {
      setLoading(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: '10px 12px',
    borderRadius: 8,
    border: '1px solid #ddd',
    fontSize: 14,
    boxSizing: 'border-box',
    outline: 'none',
  };

  const labelStyle: React.CSSProperties = {
    display: 'block',
    fontSize: 12,
    color: '#555',
    marginBottom: 4,
    fontWeight: 500,
  };

  return (
    <div style={{ minHeight: '100vh', background: '#fafafa', fontFamily: 'system-ui, sans-serif' }}>

      {/* Header */}
      <div style={{ background: '#1a1a2e', color: 'white', padding: '16px 24px' }}>
        <div style={{ maxWidth: 720, margin: '0 auto', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 600 }}>Dutch AVM</div>
            <div style={{ fontSize: 12, opacity: 0.6, marginTop: 2 }}>Automated Valuation Model</div>
          </div>
          <div style={{ fontSize: 11, opacity: 0.5 }}>XGBoost · BAG · WOZ · Snowflake</div>
        </div>
      </div>

      {/* Main */}
      <div style={{ maxWidth: 720, margin: '0 auto', padding: '32px 24px' }}>

        {/* Form */}
        <div style={{
          background: 'white',
          borderRadius: 16,
          padding: 24,
          border: '0.5px solid #e0e0e0',
          marginBottom: 24,
        }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 20px', color: '#1a1a2e' }}>
            Woning taxeren
          </h2>

          <form onSubmit={handleSubmit}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>

              <div>
                <label style={labelStyle}>Postcode</label>
                <input
                  style={inputStyle}
                  value={form.postcode}
                  onChange={e => setForm({ ...form, postcode: e.target.value.toUpperCase() })}
                  placeholder="3011AA"
                  maxLength={6}
                />
              </div>

              <div>
                <label style={labelStyle}>Huisnummer</label>
                <input
                  style={inputStyle}
                  type="number"
                  value={form.huisnummer}
                  onChange={e => setForm({ ...form, huisnummer: parseInt(e.target.value) || 1 })}
                  min={1}
                  max={9999}
                />
              </div>

              <div>
                <label style={labelStyle}>Oppervlakte (m²)</label>
                <input
                  style={inputStyle}
                  type="number"
                  value={form.oppervlakte_m2}
                  onChange={e => setForm({ ...form, oppervlakte_m2: parseFloat(e.target.value) || 85 })}
                  min={15}
                  max={500}
                  step={1}
                />
              </div>

              <div>
                <label style={labelStyle}>Energielabel</label>
                <select
                  style={inputStyle}
                  value={form.energielabel}
                  onChange={e => setForm({ ...form, energielabel: e.target.value })}
                >
                  {ENERGIELABELS.map(l => (
                    <option key={l} value={l}>{l}</option>
                  ))}
                </select>
              </div>

              <div>
                <label style={labelStyle}>Gebruiksdoel</label>
                <select
                  style={inputStyle}
                  value={form.gebruiksdoel}
                  onChange={e => setForm({ ...form, gebruiksdoel: e.target.value })}
                >
                  <option value="wonen">Wonen</option>
                  <option value="kantoor">Kantoor</option>
                  <option value="winkel">Winkel</option>
                </select>
              </div>

              <div>
                <label style={labelStyle}>Bouwjaar</label>
                <input
                  style={inputStyle}
                  type="number"
                  value={form.bouwjaar || ''}
                  onChange={e => setForm({ ...form, bouwjaar: parseInt(e.target.value) || undefined })}
                  min={1600}
                  max={2024}
                  placeholder="1985"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              style={{
                width: '100%',
                padding: '14px',
                background: loading ? '#999' : '#1a1a2e',
                color: 'white',
                border: 'none',
                borderRadius: 10,
                fontSize: 15,
                fontWeight: 500,
                cursor: loading ? 'not-allowed' : 'pointer',
                transition: 'background 0.2s',
              }}
            >
              {loading ? 'Berekenen...' : 'Waarde berekenen →'}
            </button>
          </form>
        </div>

        {/* Error */}
        {error && (
          <div style={{
            background: '#fff0f0',
            border: '0.5px solid #ffcccc',
            borderRadius: 12,
            padding: 16,
            color: '#cc0000',
            fontSize: 14,
            marginBottom: 24,
          }}>
            ⚠ {error}
          </div>
        )}

        {/* Result */}
        {result && (
          <div style={{
            background: 'white',
            borderRadius: 16,
            padding: 24,
            border: '0.5px solid #e0e0e0',
          }}>

            {/* Main price */}
            <div style={{ textAlign: 'center', marginBottom: 24, paddingBottom: 24, borderBottom: '0.5px solid #f0f0f0' }}>
              <div style={{ fontSize: 12, color: '#666', marginBottom: 8 }}>Geschatte waarde</div>
              <div style={{ fontSize: 48, fontWeight: 700, color: '#1a1a2e', lineHeight: 1.1 }}>
                {formatEUR(result.estimated_value)}
              </div>
              <div style={{ fontSize: 13, color: '#888', marginTop: 8 }}>
                80% betrouwbaarheidsinterval:&nbsp;
                <strong>{formatEUR(result.confidence_low)}</strong>
                &nbsp;–&nbsp;
                <strong>{formatEUR(result.confidence_high)}</strong>
              </div>
            </div>

            {/* Stats */}
            <div style={{ display: 'flex', gap: 12, marginBottom: 24 }}>
              <StatCard
                label="Prijs per m²"
                value={formatEUR(result.price_per_m2)}
                sub={`${form.oppervlakte_m2} m²`}
              />
              <StatCard
                label="Model"
                value={result.model_version}
                sub={result.plan + ' plan'}
              />
              <StatCard
                label="Bandbreedte"
                value={`±12%`}
                sub="80% CI"
              />
            </div>

            {/* SHAP chart */}
            {result.top_factors.length > 0 && (
              <SHAPChart factors={result.top_factors} />
            )}

            {/* Comparables */}
            {result.comparable_properties.length > 0 && (
              <div style={{ marginTop: 24 }}>
                <h3 style={{ fontSize: 14, fontWeight: 500, color: '#333', marginBottom: 12 }}>
                  Vergelijkbare woningen
                </h3>
                <div style={{ display: 'flex', gap: 12 }}>
                  {result.comparable_properties.map((p, i) => (
                    <ComparableCard key={i} prop={p} />
                  ))}
                </div>
              </div>
            )}

            {/* Footer */}
            <div style={{ marginTop: 20, fontSize: 11, color: '#bbb', textAlign: 'right' }}>
              {new Date(result.timestamp).toLocaleString('nl-NL')}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default App;
