# utils/html_renderer.py
"""
Enhanced HTML rendering for SMS pricing summaries.
Includes statistics cards, anomaly highlighting, and better styling.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Dict


def render_summary_html(diff: Dict, title: str = "Daily SMS Price Changes") -> str:
    """
    Generate enhanced HTML summary with statistics and anomaly detection.
    
    Args:
        diff: Diff dictionary with 'changed', 'new', 'removed', 'anomalies', 'summary'
        title: Report title
    
    Returns:
        HTML string
    """
    summary = diff.get("summary", {})
    anomalies = diff.get("anomalies", [])
    
    # Build HTML
    parts = [
        _html_head(title),
        _html_header(title),
        _html_statistics(summary),
        _html_anomalies(anomalies),
        _html_changes_table(diff.get("changed", [])),
        _html_new_routes_table(diff.get("new", [])),
        _html_removed_routes_table(diff.get("removed", [])),
        _html_footer(summary),
        "</body></html>"
    ]
    
    return "\n".join(parts)


def _html_head(title: str) -> str:
    """Generate HTML head with styling."""
    return f"""<html>
<head>
<meta charset='utf-8'>
<title>{title}</title>
<style>
* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}

body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    padding: 20px;
    min-height: 100vh;
}}

.container {{
    max-width: 1400px;
    margin: 0 auto;
    background: white;
    border-radius: 16px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.3);
    overflow: hidden;
}}

.header {{
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 40px;
    text-align: center;
}}

.header h1 {{
    font-size: 32px;
    font-weight: 700;
    margin-bottom: 8px;
}}

.header .subtitle {{
    font-size: 14px;
    opacity: 0.9;
}}

.content {{
    padding: 40px;
}}

.stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 20px;
    margin-bottom: 40px;
}}

.stat-card {{
    background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
    padding: 24px;
    border-radius: 12px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    transition: transform 0.2s;
}}

.stat-card:hover {{
    transform: translateY(-4px);
    box-shadow: 0 8px 24px rgba(0,0,0,0.15);
}}

.stat-card.highlight {{
    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
    color: white;
}}

.stat-card.success {{
    background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
    color: white;
}}

.stat-value {{
    font-size: 36px;
    font-weight: 700;
    margin-bottom: 8px;
}}

.stat-label {{
    font-size: 13px;
    opacity: 0.8;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

.anomalies {{
    margin-bottom: 40px;
}}

.anomaly-card {{
    background: #fff3cd;
    border-left: 4px solid #ffc107;
    padding: 16px;
    margin-bottom: 12px;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}}

.anomaly-card.critical {{
    background: #f8d7da;
    border-left-color: #dc3545;
}}

.anomaly-card.high {{
    background: #ffe5e5;
    border-left-color: #ff6b6b;
}}

.anomaly-header {{
    font-weight: 600;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 8px;
}}

.anomaly-badge {{
    display: inline-block;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
}}

.badge-critical {{ background: #dc3545; color: white; }}
.badge-high {{ background: #ff6b6b; color: white; }}
.badge-medium {{ background: #ffc107; color: #000; }}

section {{
    margin-bottom: 40px;
}}

h2 {{
    font-size: 24px;
    margin-bottom: 20px;
    color: #2c3e50;
    border-bottom: 3px solid #667eea;
    padding-bottom: 8px;
}}

table {{
    width: 100%;
    border-collapse: collapse;
    background: white;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    border-radius: 8px;
    overflow: hidden;
}}

thead {{
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
}}

th {{
    padding: 16px;
    text-align: left;
    font-weight: 600;
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

td {{
    padding: 14px 16px;
    border-bottom: 1px solid #ecf0f1;
    font-size: 14px;
}}

tbody tr:hover {{
    background: #f8f9fa;
}}

.price-increase {{
    background: #ffe5e5 !important;
}}

.price-decrease {{
    background: #d4edda !important;
}}

.price-new {{
    background: #d1ecf1 !important;
}}

.number {{
    font-family: 'Courier New', monospace;
    font-weight: 600;
}}

.positive {{
    color: #28a745;
}}

.negative {{
    color: #dc3545;
}}

.footer {{
    padding: 30px 40px;
    background: #f8f9fa;
    border-top: 1px solid #dee2e6;
    text-align: center;
    color: #6c757d;
    font-size: 13px;
}}

.no-data {{
    padding: 40px;
    text-align: center;
    color: #6c757d;
    font-style: italic;
}}
</style>
</head>
<body>
<div class="container">
"""


def _html_header(title: str) -> str:
    """Generate header section."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<div class="header">
    <h1>{title}</h1>
    <div class="subtitle">Generated on {timestamp}</div>
</div>
<div class="content">
"""


def _html_statistics(summary: Dict) -> str:
    """Generate statistics cards."""
    total_changes = summary.get("changes_count", 0)
    new_routes = summary.get("new_count", 0)
    removed = summary.get("removed_count", 0)
    anomalies = summary.get("anomalies_count", 0)
    avg_change = summary.get("avg_change", 0)
    increases = summary.get("increases_count", 0)
    decreases = summary.get("decreases_count", 0)
    
    cards = []
    
    # Total changes card
    cards.append(f"""
    <div class="stat-card {'highlight' if total_changes > 0 else ''}">
        <div class="stat-value">{total_changes}</div>
        <div class="stat-label">Price Changes</div>
    </div>
    """)
    
    # New routes card
    cards.append(f"""
    <div class="stat-card {'success' if new_routes > 0 else ''}">
        <div class="stat-value">{new_routes}</div>
        <div class="stat-label">New Routes</div>
    </div>
    """)
    
    # Removed routes card
    cards.append(f"""
    <div class="stat-card">
        <div class="stat-value">{removed}</div>
        <div class="stat-label">Removed</div>
    </div>
    """)
    
    # Anomalies card
    if anomalies > 0:
        cards.append(f"""
        <div class="stat-card highlight">
            <div class="stat-value">⚠️ {anomalies}</div>
            <div class="stat-label">Anomalies</div>
        </div>
        """)
    
    # Average change card
    cards.append(f"""
    <div class="stat-card">
        <div class="stat-value number {'positive' if avg_change > 0 else 'negative' if avg_change < 0 else ''}">{avg_change:+.4f}€</div>
        <div class="stat-label">Avg Change</div>
    </div>
    """)
    
    # Increases/Decreases
    cards.append(f"""
    <div class="stat-card">
        <div class="stat-value">
            <span class="positive">▲{increases}</span> / 
            <span class="negative">▼{decreases}</span>
        </div>
        <div class="stat-label">Increases / Decreases</div>
    </div>
    """)
    
    return f'<div class="stats-grid">{"".join(cards)}</div>'


def _html_anomalies(anomalies: List[Dict]) -> str:
    """Generate anomalies section."""
    if not anomalies:
        return ""
    
    html = '<section class="anomalies"><h2>⚠️ Anomalies Detected</h2>'
    
    for a in anomalies:
        severity = a.get("severity", "medium")
        anomaly_type = a.get("anomaly_type", "unknown")
        reason = a.get("reason", "No reason provided")
        pct_change = a.get("percent_change", 0)
        
        after = a.get("after", {})
        country = after.get("country", "")
        operator = after.get("operator", "")
        provider = after.get("provider", "")
        
        html += f"""
        <div class="anomaly-card {severity}">
            <div class="anomaly-header">
                <span class="anomaly-badge badge-{severity}">{severity.upper()}</span>
                <strong>{country} - {operator}</strong> ({provider})
            </div>
            <div>{reason}</div>
            <div style="margin-top:8px;font-size:12px;color:#6c757d;">
                Type: {anomaly_type} | Change: {pct_change:+.1f}%
            </div>
        </div>
        """
    
    html += '</section>'
    return html


def _html_changes_table(changes: List[Dict]) -> str:
    """Generate changed prices table."""
    if not changes:
        return '<section><h2>Changed Prices</h2><div class="no-data">No price changes detected</div></section>'
    
    html = """<section>
    <h2>Changed Prices</h2>
    <table>
    <thead>
        <tr>
            <th>Provider</th>
            <th>Country</th>
            <th>Operator</th>
            <th>Old Price</th>
            <th>New Price</th>
            <th>Change</th>
            <th>%</th>
        </tr>
    </thead>
    <tbody>
    """
    
    for c in changes:
        before = c.get("before", {})
        after = c.get("after", {})
        delta = c.get("delta", 0)
        pct = c.get("percent_change", 0)
        
        old_price = before.get("normalized_price") or before.get("new_price") or before.get("price", 0)
        new_price = after.get("normalized_price") or after.get("new_price") or after.get("price", 0)
        currency = after.get("base_currency") or after.get("currency", "EUR")
        
        row_class = "price-increase" if delta > 0 else "price-decrease"
        
        html += f"""
        <tr class="{row_class}">
            <td>{after.get('provider', '')}</td>
            <td>{after.get('country', '')}</td>
            <td>{after.get('operator', '')}</td>
            <td class="number">{old_price:.6f}</td>
            <td class="number">{new_price:.6f}</td>
            <td class="number {'positive' if delta > 0 else 'negative'}">{delta:+.6f} {currency}</td>
            <td class="number {'positive' if delta > 0 else 'negative'}">{pct:+.1f}%</td>
        </tr>
        """
    
    html += "</tbody></table></section>"
    return html


def _html_new_routes_table(new_routes: List[Dict]) -> str:
    """Generate new routes table."""
    if not new_routes:
        return '<section><h2>New Routes</h2><div class="no-data">No new routes added</div></section>'
    
    html = """<section>
    <h2>New Routes</h2>
    <table>
    <thead>
        <tr>
            <th>Provider</th>
            <th>Country</th>
            <th>Operator</th>
            <th>Price</th>
            <th>Currency</th>
        </tr>
    </thead>
    <tbody>
    """
    
    for r in new_routes:
        price = r.get("normalized_price") or r.get("new_price") or r.get("price", 0)
        currency = r.get("base_currency") or r.get("currency", "EUR")
        
        html += f"""
        <tr class="price-new">
            <td>{r.get('provider', '')}</td>
            <td>{r.get('country', '')}</td>
            <td>{r.get('operator', '')}</td>
            <td class="number">{price:.6f}</td>
            <td>{currency}</td>
        </tr>
        """
    
    html += "</tbody></table></section>"
    return html


def _html_removed_routes_table(removed: List[Dict]) -> str:
    """Generate removed routes table."""
    if not removed:
        return '<section><h2>Removed Routes</h2><div class="no-data">No routes removed</div></section>'
    
    html = """<section>
    <h2>Removed Routes</h2>
    <table>
    <thead>
        <tr>
            <th>Provider</th>
            <th>Country</th>
            <th>Operator</th>
            <th>Last Price</th>
            <th>Currency</th>
        </tr>
    </thead>
    <tbody>
    """
    
    for r in removed:
        price = r.get("normalized_price") or r.get("new_price") or r.get("price", 0)
        currency = r.get("base_currency") or r.get("currency", "EUR")
        
        html += f"""
        <tr>
            <td>{r.get('provider', '')}</td>
            <td>{r.get('country', '')}</td>
            <td>{r.get('operator', '')}</td>
            <td class="number">{price:.6f}</td>
            <td>{currency}</td>
        </tr>
        """
    
    html += "</tbody></table></section>"
    return html


def _html_footer(summary: Dict) -> str:
    """Generate footer."""
    unchanged = summary.get("unchanged", 0)
    return f"""</div>
<div class="footer">
    <div>Unchanged price pairs: {unchanged}</div>
    <div style="margin-top:8px;">Generated by SMS Price Monitoring Agent</div>
</div>
"""