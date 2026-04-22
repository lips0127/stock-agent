import { View, Text } from '@tarojs/components'
import { useLoad } from '@tarojs/taro'
import { useSelector, useDispatch } from 'react-redux'
import { RootState } from '../../store'
import { fetchIndices } from '../../store/slices/marketSlice'
import './index.scss'

export default function Index() {
  const dispatch = useDispatch()
  const indices = useSelector((state: RootState) => state.market.indices)

  useLoad(() => {
    console.log('Page loaded.')
    // @ts-ignore
    dispatch(fetchIndices())
  })

  return (
    <View className='index'>
      <Text className='title'>Market Indices</Text>
      <View className='indices-list'>
        {indices.map((index: any) => (
          <View key={index.symbol} className='index-item'>
            <Text>{index.name}</Text>
            <Text>{index.current}</Text>
          </View>
        ))}
      </View>
    </View>
  )
}
