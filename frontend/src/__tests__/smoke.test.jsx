import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { PChip } from '../components/Chip';

describe('test setup', () => {
  it('renders a component in jsdom and finds it by what a user sees', () => {
    render(<PChip p="Critical" />);
    expect(screen.getByText('Critical')).toBeInTheDocument();
  });
});
