import { formatDay, HEALTH_LABELS, VERDICT_LABELS } from './constants';

const SITE_URL = 'https://thomas-amann-ipaustralia.github.io/ai-steward-dashboard';

/**
 * Builds a plain-markdown digest of the last seven days.
 *
 * Stewards forward this sort of thing to their team. One button beats a
 * copy-paste job, and it is a fraction of the work of a PDF export.
 */
export function buildBriefing({ recentChanges = [], failingSources = [], stableCount = 0, generatedAt = new Date() }) {
  const lines = [
    `# AI policy watch — ${formatDay(generatedAt.toISOString())}`,
    '',
  ];

  if (failingSources.length > 0) {
    lines.push('## Needs attention', '');
    failingSources.forEach((source) => {
      lines.push(
        `- **${source.setName}** — ${HEALTH_LABELS[source.status] || source.status}` +
          (source.last_success ? ` (last complete read ${formatDay(source.last_success)})` : ' (never read successfully)')
      );
    });
    lines.push('');
  }

  lines.push('## Changes in the last 7 days', '');
  if (recentChanges.length === 0) {
    lines.push('No policy changes detected.', '');
  } else {
    recentChanges.forEach((change) => {
      const priority = (change.last_priority || 'unrated').toUpperCase();
      lines.push(`### ${change.setName} — ${priority}`);
      lines.push(`Changed ${formatDay(change.last_amended)}`);
      if (change.last_change?.changed_documents?.length) {
        lines.push(`Documents: ${change.last_change.changed_documents.join(', ')}`);
      }
      if (change.last_review?.summary) {
        lines.push('', change.last_review.summary);
      }
      lines.push('', `${SITE_URL}/#/policy/${change.file_id}`, '');
    });
  }

  lines.push(
    '## Checked and unchanged',
    '',
    `${stableCount} monitored policy set${stableCount === 1 ? '' : 's'} were checked and showed no material change.`,
    '',
    '---',
    `Generated from ${SITE_URL}`
  );

  return lines.join('\n');
}

export function verdictLabel(verdict) {
  return VERDICT_LABELS[verdict] || null;
}

export async function copyToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return true;
  }

  // Fallback for browsers where the async clipboard API is unavailable or
  // blocked by policy, which is not unusual on managed agency devices.
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'absolute';
  area.style.left = '-9999px';
  document.body.appendChild(area);
  area.select();
  const ok = document.execCommand('copy');
  document.body.removeChild(area);
  return ok;
}
