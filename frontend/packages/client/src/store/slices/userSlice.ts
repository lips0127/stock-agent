import { createSlice, PayloadAction } from '@reduxjs/toolkit'

interface UserState {
  token: string | null
  userInfo: any | null
}

const initialState: UserState = {
  token: null,
  userInfo: null
}

export const userSlice = createSlice({
  name: 'user',
  initialState,
  reducers: {
    setToken: (state, action: PayloadAction<string>) => {
      state.token = action.payload
    },
    setUserInfo: (state, action: PayloadAction<any>) => {
      state.userInfo = action.payload
    },
    logout: (state) => {
      state.token = null
      state.userInfo = null
    }
  }
})

export const { setToken, setUserInfo, logout } = userSlice.actions

export default userSlice.reducer
