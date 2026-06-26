function ValueRange({ valueRange, dataType }) {
  if (!valueRange) return null

  if (valueRange.type === 'empty') {
    return <span className="value-range empty">Empty column</span>
  }

  if (valueRange.type === 'numeric') {
    return (
      <span className="value-range numeric">
        Min: {valueRange.min}, Max: {valueRange.max}
      </span>
    )
  }

  if (valueRange.type === 'text') {
    return (
      <span className="value-range text">
        Unique values: {valueRange.unique_count}
        {valueRange.sample_values && valueRange.sample_values.length > 0 && (
          <div className="sample-values">
            Samples: {valueRange.sample_values.slice(0, 5).join(', ')}
            {valueRange.sample_values.length > 5 && '...'}
          </div>
        )}
      </span>
    )
  }

  return null
}

export default ValueRange
