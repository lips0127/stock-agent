import Taro from '@tarojs/taro'

const BASE_URL = process.env.TARO_ENV === 'h5' ? '' : 'https://api.stockagent.com'

const request = async (options: Taro.request.Option) => {
  const { url, data, method = 'GET' } = options
  
  // Get token from storage
  const token = Taro.getStorageSync('token')
  
  const header = {
    'Content-Type': 'application/json',
    'Authorization': token ? `Bearer ${token}` : ''
  }

  try {
    const response = await Taro.request({
      url: BASE_URL + url,
      data,
      method,
      header
    })

    if (response.statusCode >= 200 && response.statusCode < 300) {
      return response.data
    } else if (response.statusCode === 401) {
      // Handle unauthorized
      Taro.navigateTo({ url: '/pages/login/index' })
      throw new Error('Unauthorized')
    } else {
      throw new Error(response.data.message || 'Network Error')
    }
  } catch (error) {
    Taro.showToast({
      title: error.message || 'Error',
      icon: 'none'
    })
    throw error
  }
}

export default request
