export const BASE_URL = process.env.PUBLIC_URL || '/ai-steward-dashboard';

export const PRIORITY_COLORS = {
  critical: '#dc2626',
  high: '#ea580c',
  medium: '#d97706',
  low: '#16a34a',
};

export const getPriorityColor = (priority) => {
  return PRIORITY_COLORS[priority?.toLowerCase()] || '#6b7280';
};

export const formatDate = (dateString) => {
  if (!dateString || dateString === 'Unknown') return 'Unknown';
  try {
    return new Date(dateString).toLocaleString('en-AU', {
      timeZone: 'Australia/Sydney',
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return dateString;
  }
};
