import request from '../utils/request'

export const login = (data: any) => {
  return request({
    url: '/api/auth/login',
    method: 'POST',
    data
  })
}

export const getIndices = () => {
  return request({
    url: '/api/market/indices',
    method: 'GET'
  })
}
