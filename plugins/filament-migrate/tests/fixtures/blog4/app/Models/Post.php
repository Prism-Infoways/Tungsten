<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Concerns\HasUlids;
use Illuminate\Database\Eloquent\Model;

class Post extends Model
{
    use HasUlids;

    protected $casts = ['published_at' => 'datetime'];

    public function author()
    {
        return $this->belongsTo(User::class, 'author_id');
    }
}
