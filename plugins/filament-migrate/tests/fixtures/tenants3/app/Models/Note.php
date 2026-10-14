<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Eloquent\Model;

class Note extends Model
{
    protected $guarded = [];

    protected static function booted(): void
    {
        static::addGlobalScope('active', function (Builder $builder) {
            $builder->where('archived', false);
        });
    }

    public function booking()
    {
        return $this->belongsTo(User::class, 'owner_id');
    }
}
