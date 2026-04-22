import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import { getIndices } from '../../services/api'

export const fetchIndices = createAsyncThunk(
  'market/fetchIndices',
  async () => {
    const response = await getIndices()
    return response
  }
)

interface MarketState {
  indices: any[]
  loading: boolean
}

const initialState: MarketState = {
  indices: [],
  loading: false
}

export const marketSlice = createSlice({
  name: 'market',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchIndices.pending, (state) => {
        state.loading = true
      })
      .addCase(fetchIndices.fulfilled, (state, action) => {
        state.loading = false
        state.indices = action.payload
      })
  }
})

export default marketSlice.reducer
