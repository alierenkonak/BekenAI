import { Fragment, type ReactNode } from 'react';

/** Fills the {name} slots of a translated sentence with elements: an italic word, a link, code. */
export function rich(text: string, slots: Record<string, ReactNode>): ReactNode {
  return text.split(/\{(\w+)\}/g).map((part, index) => (index % 2 === 1 ? <Fragment key={index}>{slots[part]}</Fragment> : part));
}
