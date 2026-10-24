import { expect, it } from 'vitest'
import { SIM_LIST } from './catalog'
import { SIMS } from './index'

it('every searchable model has exactly the metadata of a registered model', () => {
  expect(SIM_LIST).toEqual(SIMS.map(({ Component: _, ...info }) => info))
})
